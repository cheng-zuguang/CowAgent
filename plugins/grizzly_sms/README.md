# GrizzlySMS 插件

根据关键词调用 GrizzlySMS 获取手机号、查询余额，并在获取号码后按激活截止时间后台轮询验证码。

## 使用方式

1. 复制 `config.json.template` 为 `config.json`
2. 填写 `api_key` 和默认取号参数，例如 `service`、`country`、`maxPrice`
3. 重启 CowAgent，或通过插件管理命令重新扫描/加载插件

## 默认关键词

- `手机号`、`手机`、`号`、`号码`：获取号码
- `余额`：查询账户余额

获取号码成功后，插件会立即返回号码和激活信息，并后台轮询。每轮先调用 `setStatus` 并传入 `status=1`，只有返回 `ACCESS_READY` 时才继续调用 `getStatusV2` 获取短信详情。轮询在以下情况终止：

- 成功获取验证码
- 到达 `activationEnd`
- `setStatus` 返回 `ACCESS_READY` 之外的业务状态
- 接口返回业务错误
- HTTP 非 2xx 或请求异常

`activationEnd` 等接口时间默认按 UTC 时间解释，回复时会转换成用户所在时区。默认使用系统本地时区；也可以将 `display_time_zone` 设置为 `Asia/Shanghai`、`UTC`、`+08:00` 等值。若接口返回的是本地时间，可将 `activation_time_zone` 改为 `local`。

如需查看每一次轮询状态，可将 `debug_polling` 设置为 `true`，日志中会输出每轮 `activationId`、`setStatus` 响应、是否调用 `getStatusV2`、是否拿到短信等信息。
