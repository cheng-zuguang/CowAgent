1.获取号码：

https://api.grizzlysms.com/stubs/handler_api.php?api_key=$api_key&action=getNumberV2&service=$service&country=$country&maxPrice=maxPrice&providerIds=$providerIds&exceptProviderIds=$exceptProviderIds
&action=getNumberV2

该方法与 getNumber 方法工作方式相同，接受相同的参数，但会返回额外的激活信息。

$api_key — 您的 API 密钥（设置）；
$service — 服务代码；
$country — 国家代码。您可以传入 “any” 或将该值留空，以便系统根据库存、价格和到达率自动选择最佳可用国家；
$maxPrice — 您愿意为一个号码支付的最高价格；
$providerIds — 将用于购买的服务商列表，以逗号分隔 (1,2,3)；
$exceptProviderIds — 从号码购买中排除的服务商列表，以逗号分隔 (1,2,3)。

可能的错误：
BAD_KEY — 请检查您的 API 密钥；
NO_BALANCE — 余额不足，请先充值；
NO_NUMBERS — 请重新发起请求或选择其他国家；
The service is prohibited for sale by administration — 请选择其他服务；
SERVICE_UNAVAILABLE_REGION — 您所在地区的访问受限，请使用其他 IP。

成功响应示例：

{
  "activationCancel": "2026-05-07 14:03:16",
  "activationCost": 0.35,
  "activationEnd": "2026-05-07 14:18:16",
  "activationId": 495357953,
  "activationTime": "2026-05-07 13:58:16",
  "canGetAnotherSms": "0",
  "countryCode": "12",
  "currency": 643,
  "phoneNumber": "18036181752"
}
其中 495357953 是激活 ID。18036181752 是电话号码，
0.35 - 购买价格，
643 - ISO 4217 货币代码，12 - 国家代码，
0/1 = true/false 表示是否支持第二条短信，
2026-05-07 13:58:16 - 激活开始时间，
2026-05-07 14:03:16 - 可取消激活的最晚时间，
2026-05-07 14:18:16 - 激活结束时间。

2.激活状态变更
https://api.grizzlysms.com/stubs/handler_api.php?api_key=$api_key&action=setStatus&status=$status&id=$id

&action=setStatus

$api_key — 您的 API 密钥（设置）；
$id — 激活 ID；
$status — 激活状态：
-1 — 取消激活
1 — 通知号码已就绪（短信已发送到该号码）；
3 — 在同一号码上等待下一个验证码；
6 — 完成激活；
8 — 取消激活。

服务响应：
ACCESS_READY — 已确认号码可用性
ACCESS_RETRY_GET — 正在等待新的短信
ACCESS_ACTIVATION — 服务已成功激活
ACCESS_CANCEL — 激活已取消

可能的错误：
ERROR_SQL — SQL 服务器错误
NO_ACTIVATION — 激活 ID 不存在
BAD_SERVICE — 服务名称不正确
BAD_STATUS — 状态不正确
BAD_KEY — 无效的 API 密钥
BAD_ACTION — 操作不正确
SERVICE_UNAVAILABLE_REGION — 您所在地区的访问受限，请使用其他 IP

3.获取激活状态
https://api.grizzlysms.com/stubs/handler_api.php?api_key=$api_key&action=getStatusV2&id=$id

&action=getStatusV2
$api_key — 您的 API 密钥（设置）；
$id — 激活 ID。

可能的错误：
NO_ACTIVATION — 激活 ID 不存在
BAD_KEY — 无效的 API 密钥
BAD_ACTION — 错误的操作
SERVICE_UNAVAILABLE_REGION — 您所在地区的访问受限，请使用其他 IP

成功响应示例：
{
    "verificationType": 2,
    "sms": {
        "dateTime": "2026-02-26 12:05:55",
        "code": "852508",
        "text": "852508"
    }
}
其中 dateTime 为激活时间，code 为短信验证码，text 为完整短信内容。


3.余额请求
https://api.grizzlysms.com/stubs/handler_api.php?api_key=$api_key&action=getBalance
&action=getBalance
$api_key — 您的 API 密钥（设置）；

服务响应：
ACCESS_BALANCE:$balance（其中 $balance 为账户余额）

可能的错误：
BAD_KEY — 无效的 API 密钥
SERVICE_UNAVAILABLE_REGION — 您所在地区的访问受限，请使用其他 IP