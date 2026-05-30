# encoding:utf-8

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import requests

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *


@plugins.register(
    name="GrizzlySms",
    desire_priority=950,
    hidden=False,
    desc="GrizzlySMS 手机号获取、验证码轮询和余额查询",
    version="0.1",
    author="Codex",
)
class GrizzlySms(Plugin):
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self):
        super().__init__()
        self.config = self._load_config()
        self.active_polls = set()
        self.poll_lock = threading.Lock()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        logger.info("[GrizzlySms] inited")

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type != ContextType.TEXT:
            return

        content = str(context.content or "").strip()
        if not content:
            return

        if content in self.config.get("keywords_get_number", []):
            reply_text = self._handle_get_number(e_context)
            e_context["reply"] = Reply(ReplyType.TEXT, reply_text)
            e_context.action = EventAction.BREAK_PASS
            return

        if content in self.config.get("keywords_balance", []):
            reply_text = self._handle_balance()
            e_context["reply"] = Reply(ReplyType.TEXT, reply_text)
            e_context.action = EventAction.BREAK_PASS

    def _handle_get_number(self, e_context: EventContext) -> str:
        ok, data, error = self._get_number()
        if not ok:
            return self._format_error("获取号码失败", error)

        activation_id = data.get("activationId")
        activation_end = data.get("activationEnd")

        if activation_id and activation_end:
            self._start_polling(e_context, str(activation_id), str(activation_end))
        else:
            logger.warning("[GrizzlySms] getNumberV2 response missing activationId or activationEnd: %s", data)

        return self._format_number(data)

    def _handle_balance(self) -> str:
        ok, balance, error = self._get_balance()
        if not ok:
            return self._format_error("查询余额失败", error)
        return "💰 余额查询成功\n\n余额：{}".format(balance)

    def _get_number(self) -> Tuple[bool, Dict[str, Any], str]:
        missing = self._missing_required(["api_key", "service"])
        if missing:
            return False, {}, "插件配置缺少：{}".format("、".join(missing))

        params = {
            "api_key": self.config.get("api_key"),
            "action": "getNumberV2",
            "service": self.config.get("service"),
        }
        self._add_optional_params(
            params,
            ["country", "maxPrice", "providerIds", "exceptProviderIds"],
        )

        ok, payload, error = self._request(params)
        if not ok:
            return False, {}, error
        if not isinstance(payload, dict):
            return False, {}, self._api_error_to_text(payload)
        if not payload.get("phoneNumber"):
            return False, {}, "接口未返回 phoneNumber：{}".format(payload)
        return True, payload, ""

    def _get_status(self, activation_id: str) -> Tuple[bool, Dict[str, Any], str]:
        if not self.config.get("api_key"):
            return False, {}, "插件配置缺少：api_key"

        ok, payload, error = self._request(
            {
                "api_key": self.config.get("api_key"),
                "action": "getStatusV2",
                "id": activation_id,
            }
        )
        if not ok:
            return False, {}, error
        if not isinstance(payload, dict):
            return False, {}, self._api_error_to_text(payload)
        sms = payload.get("sms")
        if isinstance(sms, dict) and (sms.get("code") or sms.get("text")):
            return True, payload, ""
        return True, payload, ""

    def _set_activation_status(self, activation_id: str, status: int = 1) -> Tuple[bool, str, str]:
        if not self.config.get("api_key"):
            return False, "", "插件配置缺少：api_key"

        ok, payload, error = self._request(
            {
                "api_key": self.config.get("api_key"),
                "action": "setStatus",
                "status": status,
                "id": activation_id,
            }
        )
        if not ok:
            return False, "", error
        if not isinstance(payload, str):
            return False, "", self._api_error_to_text(payload)
        if payload == "ACCESS_READY":
            return True, payload, ""
        if payload in ("ACCESS_RETRY_GET", "ACCESS_ACTIVATION", "ACCESS_CANCEL"):
            return True, payload, ""
        return False, "", self._api_error_to_text(payload)

    def _get_balance(self) -> Tuple[bool, str, str]:
        if not self.config.get("api_key"):
            return False, "", "插件配置缺少：api_key"

        ok, payload, error = self._request(
            {
                "api_key": self.config.get("api_key"),
                "action": "getBalance",
            }
        )
        if not ok:
            return False, "", error

        if isinstance(payload, str) and payload.startswith("ACCESS_BALANCE:"):
            return True, payload.split(":", 1)[1], ""
        return False, "", self._api_error_to_text(payload)

    def _request(self, params: Dict[str, Any]) -> Tuple[bool, Any, str]:
        try:
            response = requests.get(
                self.config.get("base_url", "https://api.grizzlysms.com/stubs/handler_api.php"),
                params=params,
                timeout=self._request_timeout(),
            )
            if response.status_code < 200 or response.status_code >= 300:
                return False, None, "HTTP {}：{}".format(response.status_code, response.text[:200])
            text = response.text.strip()
            if not text:
                return False, None, "接口返回为空"
            try:
                return True, response.json(), ""
            except ValueError:
                return True, text, ""
        except requests.RequestException as e:
            return False, None, self._format_request_exception(e)

    def _start_polling(self, e_context: EventContext, activation_id: str, activation_end: str):
        with self.poll_lock:
            if activation_id in self.active_polls:
                return
            self.active_polls.add(activation_id)

        thread = threading.Thread(
            target=self._poll_status,
            args=(e_context, activation_id, activation_end),
            daemon=True,
        )
        thread.start()
        logger.info("[GrizzlySms] polling started, activation_id=%s, activation_end=%s", activation_id, activation_end)

    def _poll_status(self, e_context: EventContext, activation_id: str, activation_end: str):
        try:
            end_time = self._parse_activation_time(activation_end)
            if not end_time:
                self._notify(e_context, self._format_error("验证码轮询终止", "无法解析 activationEnd：{}".format(activation_end)))
                return

            while datetime.now(timezone.utc) < end_time:
                time.sleep(self._poll_interval())
                status_ok, status_payload, status_error = self._set_activation_status(activation_id, 1)
                self._log_set_status_poll(activation_id, status_ok, status_payload, status_error)
                if not status_ok:
                    self._notify(e_context, self._format_error("验证码轮询已终止", "setStatus 请求失败：{}".format(status_error)))
                    return
                if status_payload != "ACCESS_READY":
                    self._notify(e_context, self._format_error("验证码轮询已终止", self._api_error_to_text(status_payload)))
                    return

                ok, payload, error = self._get_status(activation_id)
                self._log_get_status_poll(activation_id, ok, payload, error)
                if not ok:
                    self._notify(e_context, self._format_error("验证码轮询已终止", error))
                    return

                sms = payload.get("sms") if isinstance(payload, dict) else None
                if isinstance(sms, dict) and (sms.get("code") or sms.get("text")):
                    self._notify(e_context, self._format_sms(activation_id, payload))
                    return

            self._notify(
                e_context,
                "⌛ 验证码轮询超时\n\n激活 ID：{}\n截止时间：{}\n未在有效期内收到验证码。".format(
                    activation_id,
                    self._format_api_time(activation_end),
                ),
            )
        finally:
            with self.poll_lock:
                self.active_polls.discard(activation_id)
            logger.info("[GrizzlySms] polling stopped, activation_id=%s", activation_id)

    def _notify(self, e_context: EventContext, text: str):
        try:
            channel = e_context["channel"]
            context = e_context["context"]
            if channel and context:
                channel.send(Reply(ReplyType.TEXT, text), context)
        except Exception as e:
            logger.warning("[GrizzlySms] notify failed: %s", e)

    def _format_number(self, data: Dict[str, Any]) -> str:
        lines = [
            "📱 获取号码成功",
            "",
            "手机号：{}".format(data.get("phoneNumber", "-")),
            "激活 ID：{}".format(data.get("activationId", "-")),
            "价格：{}".format(data.get("activationCost", "-")),
            "货币代码：{}".format(data.get("currency", "-")),
            "国家代码：{}".format(data.get("countryCode", "-")),
            "开始时间：{}".format(self._format_api_time(data.get("activationTime"))),
            "取消截止：{}".format(self._format_api_time(data.get("activationCancel"))),
            "激活截止：{}".format(self._format_api_time(data.get("activationEnd"))),
            "支持第二条短信：{}".format(self._yes_no(data.get("canGetAnotherSms"))),
            "",
            "已开始后台轮询验证码，收到后会自动发给你。",
        ]
        return "\n".join(lines)

    def _format_sms(self, activation_id: str, data: Dict[str, Any]) -> str:
        sms = data.get("sms") or {}
        return "\n".join(
            [
                "✅ 验证码已收到",
                "",
                "激活 ID：{}".format(activation_id),
                "验证码：{}".format(sms.get("code", "-")),
                "短信内容：{}".format(sms.get("text", "-")),
                "接收时间：{}".format(self._format_api_time(sms.get("dateTime"))),
            ]
        )

    def _format_error(self, title: str, error: str) -> str:
        return "❌ {}\n\n原因：{}".format(title, error or "未知错误")

    def _api_error_to_text(self, payload: Any) -> str:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        error_map = {
            "BAD_KEY": "API Key 无效，请检查配置",
            "NO_BALANCE": "余额不足，请先充值",
            "NO_NUMBERS": "暂无可用号码，请稍后重试或调整国家/服务",
            "NO_ACTIVATION": "激活 ID 不存在或已失效",
            "BAD_ACTION": "接口 action 参数错误",
            "SERVICE_UNAVAILABLE_REGION": "当前地区访问受限，请更换网络或 IP",
            "The service is prohibited for sale by administration": "该服务已被限制销售，请更换服务",
            "ERROR_SQL": "SQL 服务器错误",
            "BAD_SERVICE": "服务名称不正确",
            "BAD_STATUS": "激活状态不正确",
            "ACCESS_RETRY_GET": "正在等待新的短信",
            "ACCESS_ACTIVATION": "服务已成功激活",
            "ACCESS_CANCEL": "激活已取消",
        }
        return error_map.get(text, text)

    def _format_request_exception(self, error: requests.RequestException) -> str:
        message = str(error)
        cause = self._root_cause(error)
        if cause:
            message = "{}；根因：{}".format(message, cause)
        if "Connection reset by peer" in message or isinstance(cause, ConnectionResetError):
            return "HTTP 请求异常：连接被对端重置。可能是上游服务、网络、代理或频繁调用 setStatus 导致。原始错误：{}".format(message)
        return "HTTP 请求异常：{}".format(message)

    def _root_cause(self, error: BaseException) -> Optional[BaseException]:
        seen = set()
        current = error
        while current and id(current) not in seen:
            seen.add(id(current))
            next_error = current.__cause__ or current.__context__
            if not next_error:
                break
            current = next_error
        return current if current is not error else None

    def _load_config(self) -> Dict[str, Any]:
        config = super().load_config()
        if config:
            return config

        template_path = os.path.join(self.path, "config.json.template")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                logger.warning("[GrizzlySms] config.json not found, using template config")
                return json.load(f)
        except Exception as e:
            logger.error("[GrizzlySms] load config failed: %s", e)
            return {}

    def _missing_required(self, keys):
        return [key for key in keys if not self.config.get(key)]

    def _add_optional_params(self, params: Dict[str, Any], keys):
        for key in keys:
            value = self.config.get(key)
            if value is not None and str(value).strip() != "":
                params[key] = value

    def _request_timeout(self) -> int:
        try:
            return max(1, int(self.config.get("request_timeout_seconds", 10)))
        except (TypeError, ValueError):
            return 10

    def _poll_interval(self) -> int:
        try:
            return max(1, int(self.config.get("poll_interval_seconds", 5)))
        except (TypeError, ValueError):
            return 5

    def _debug_polling_enabled(self) -> bool:
        return bool(self.config.get("debug_polling", False))

    def _log_set_status_poll(self, activation_id: str, ok: bool, payload: str, error: str):
        if not self._debug_polling_enabled():
            return

        if not ok:
            logger.info("[GrizzlySms] poll setStatus activation_id=%s ok=false error=%s", activation_id, error)
            return

        logger.info(
            "[GrizzlySms] poll setStatus activation_id=%s ok=true response=%s",
            activation_id,
            payload,
        )

    def _log_get_status_poll(self, activation_id: str, ok: bool, payload: Any, error: str):
        if not self._debug_polling_enabled():
            return

        if not ok:
            logger.info("[GrizzlySms] poll getStatusV2 activation_id=%s ok=false error=%s", activation_id, error)
            return

        sms = payload.get("sms") if isinstance(payload, dict) else None
        has_sms = isinstance(sms, dict) and bool(sms.get("code") or sms.get("text"))
        logger.info(
            "[GrizzlySms] poll getStatusV2 activation_id=%s ok=true has_sms=%s payload=%s",
            activation_id,
            has_sms,
            payload,
        )

    def _parse_activation_time(self, value: str) -> Optional[datetime]:
        """Parse activation timestamps and normalize to UTC.

        GrizzlySMS returns activationEnd in UTC. Some responses omit timezone
        info, while others may use ISO-8601 offsets. Treat naive values as UTC
        by default, with a config escape hatch for older local-time setups.
        """
        if not value:
            return None

        text = str(value).strip()
        normalized = text
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        elif normalized.upper().endswith(" UTC"):
            normalized = normalized[:-4] + "+00:00"

        parsed = None
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            pass

        if parsed is None:
            try:
                parsed = datetime.strptime(text, self.DATE_FORMAT)
            except (TypeError, ValueError):
                return None

        if parsed.tzinfo is None:
            if self._activation_time_zone() == "local":
                parsed = parsed.astimezone()
            else:
                parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    def _format_api_time(self, value: Any) -> str:
        if not value:
            return "-"
        parsed = self._parse_activation_time(str(value))
        if not parsed:
            return str(value)
        display_tz = self._display_timezone()
        display_time = parsed.astimezone(display_tz)
        return "{} ({})".format(
            display_time.strftime(self.DATE_FORMAT),
            self._format_timezone_label(display_time),
        )

    def _activation_time_zone(self) -> str:
        zone = str(self.config.get("activation_time_zone", "UTC")).strip().lower()
        if zone in ("local", "system"):
            return "local"
        return "utc"

    def _display_timezone(self):
        zone = str(self.config.get("display_time_zone", "local")).strip()
        zone_lower = zone.lower()
        if not zone or zone_lower in ("local", "system"):
            return datetime.now().astimezone().tzinfo
        if zone_lower in ("utc", "z"):
            return timezone.utc

        fixed_offset = self._parse_fixed_timezone(zone)
        if fixed_offset:
            return fixed_offset

        if ZoneInfo:
            try:
                return ZoneInfo(zone)
            except Exception:
                logger.warning("[GrizzlySms] invalid display_time_zone=%s, fallback to local timezone", zone)

        return datetime.now().astimezone().tzinfo

    def _parse_fixed_timezone(self, value: str):
        text = value.strip().upper()
        if text.startswith("UTC"):
            text = text[3:].strip()
        if text.startswith("GMT"):
            text = text[3:].strip()
        if not text:
            return timezone.utc
        if text[0] not in ("+", "-"):
            return None

        sign = 1 if text[0] == "+" else -1
        body = text[1:]
        try:
            if ":" in body:
                hours_text, minutes_text = body.split(":", 1)
                hours = int(hours_text)
                minutes = int(minutes_text)
            else:
                hours = int(body)
                minutes = 0
        except ValueError:
            return None

        if hours > 23 or minutes > 59:
            return None
        offset = timedelta(hours=hours, minutes=minutes) * sign
        return timezone(offset)

    def _format_timezone_label(self, value: datetime) -> str:
        offset = value.utcoffset()
        if offset is None:
            return "本地时区"
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        abs_minutes = abs(total_minutes)
        hours, minutes = divmod(abs_minutes, 60)
        return "UTC{}{:02d}:{:02d}".format(sign, hours, minutes)

    def _yes_no(self, value: Any) -> str:
        return "是" if str(value) == "1" else "否"

    def get_help_text(self, **kwargs):
        return "输入 手机号/手机/号/号码 获取号码并后台轮询验证码；输入 余额 查询账户余额。"
