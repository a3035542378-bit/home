"""Content-free diagnostics for the current binding of one WeChat group."""
from . import agent_wechat, native_voice


_RECENT = """
WITH target AS (
    SELECT g.id, g.account, g.binding FROM groups g JOIN account a ON a.id=g.account
    WHERE g.id=:group AND a.mode='adapter'
), events AS (
    SELECT d.source_time received, i.seq record_id, 'text' kind, i.seq, NULL voice_state
    FROM target g JOIN inbox i ON i.grp=g.id AND i.account=g.account AND i.binding=g.binding
    JOIN directed_events d ON d.biz=i.event_id
    WHERE i.kind='message' AND i.message_type='text' AND i.adapter_version=:text_version
    UNION ALL
    SELECT v.source_time, v.id, 'voice', i.seq, v.state
    FROM target g JOIN native_voice_events v
      ON v.grp=g.id AND v.account=g.account AND v.binding=g.binding
    LEFT JOIN inbox i ON i.seq=v.seq AND i.grp=v.grp AND i.account=v.account
      AND i.binding=v.binding AND i.source=v.source AND i.kind='message'
      AND i.message_type='voice' AND i.adapter_version=:voice_version
), latest AS (
    SELECT * FROM events ORDER BY received DESC, record_id DESC, kind LIMIT :limit
)
SELECT e.received, e.kind, e.voice_state, i.state input_state, o.state output_state,
       o.detail receipt, o.ack_at, COALESCE(o.attempts,0) attempts,
       c.state model_state, q.state query_state
FROM latest e LEFT JOIN inbox i ON i.seq=e.seq
LEFT JOIN outbox o ON o.biz=i.event_id AND o.grp=i.grp AND o.account=i.account AND o.binding=i.binding
LEFT JOIN chat_requests c ON c.seq=i.seq LEFT JOIN queries q ON q.id=i.seq
ORDER BY e.received DESC, e.record_id DESC, e.kind
"""

_VOICE_STATES = {
    "PENDING": ("等待识别", "语音已进入处理队列"),
    "PROCESSING": ("识别中", "正在准备或识别这条语音"),
    "NOT_ADDRESSED": ("未唤醒", "识别结果未匹配唤醒词"),
    "EXPIRED": ("语音已过期", "语音处理时限已过"),
    "CANCELLED": ("语音处理已取消", "本次语音处理已停止"),
    "RATE_LIMITED": ("语音识别受限", "已达到本群语音识别频率上限"),
    "FAILED": ("语音处理失败", "语音未完成识别或指令登记"),
}
_SEND_STATES = {
    "PENDING": ("等待发送", "已生成回复任务"),
    "RETRY_WAIT": ("等待重试", "回复任务正在等待下次尝试"),
    "SENDING": ("发送中", "正在等待发送结果"),
    "FAILED": ("发送失败", "本次回复任务已失败"),
    "EXPIRED": ("回复已过期", "发送时限已过"),
    "CANCELLED": ("发送已取消", "回复任务已取消"),
    "UNKNOWN": ("发送结果待核对", "无法确认本次投递结果"),
}
_WORK_STATES = {
    "PENDING": "等待处理", "RUNNING": "处理中", "FAILED": "失败",
    "CANCELLED": "已取消", "EXPIRED": "已过期",
}
_INBOX_STATES = {
    "PENDING": ("等待处理", "已进入指令队列"),
    "RATE_LIMITED": ("指令受限", "已达到本群指令频率上限"),
    "IGNORED": ("已忽略", "指令未继续处理"),
    "REJECTED": ("指令未通过", "未登记回复任务"),
    "FAILED": ("指令处理失败", "业务处理未完成"),
    "EXPIRED": ("指令已过期", "处理时限已过"),
}


def _delivery(row):
    state, receipt = row["output_state"], row["receipt"]
    if receipt == "管理员核对":
        if state == "ACKNOWLEDGED":
            return "人工确认送达", "管理员已核对投递结果"
        if state == "CANCELLED":
            return "人工结束跟进", "管理员已结束本次跟进"
    if state == "ACKNOWLEDGED":
        verified = ("已核对本群原生语音的微信回执和发件记录" if row["kind"] == "voice"
                    else "微信已受理，已回读核对本群发件记录")
        if receipt == verified:
            return "微信发件已核对", "已核对微信回执及本群发件记录"
        if receipt == "微信已受理，发件记录暂未核验" and row["kind"] == "text":
            return "微信已受理", "尚未核对本群发件记录"
        return "任务已确认", "记录未注明微信发件核验方式"
    return _SEND_STATES.get(state, ("发送状态待核对", "回复任务状态尚未识别"))


def _summary(row):
    if row["voice_state"] and row["voice_state"] != "AWAKE":
        return _VOICE_STATES.get(row["voice_state"], ("语音状态待核对", "语音处理状态尚未识别"))
    if row["output_state"]:
        status, detail = _delivery(row)
        if row["model_state"] == "FAILED":
            detail += "。本次模型请求失败"
        if row["query_state"] == "FAILED":
            detail += "。本次生活查询失败"
        return status, detail
    for label, state in (("模型请求", row["model_state"]), ("生活查询", row["query_state"])):
        if state in _WORK_STATES:
            return label + _WORK_STATES[state], "尚无回复发送记录"
    if row["input_state"] in _INBOX_STATES:
        return _INBOX_STATES[row["input_state"]]
    return "暂无发送记录", "已识别唤醒词" if row["kind"] == "voice" else "已登记点名文字"


def recent(db, group, limit=10):
    """Newest provider message timestamps, including unaddressed authorized voice notes."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("记录数量须为 1 至 100")
    rows = db.execute(_RECENT, dict(group=group, limit=limit, text_version=agent_wechat.VERSION,
                                    voice_version=native_voice.VERSION))
    records = []
    for row in rows:
        status, detail = _summary(row)
        ack_at = row["ack_at"] if row["output_state"] == "ACKNOWLEDGED" and row["receipt"] != "管理员核对" else None
        records.append(dict(received=row["received"], kind="群语音" if row["kind"] == "voice" else "点名文字",
                            status=status, attempts=row["attempts"], ack_at=ack_at, detail=detail))
    return records
