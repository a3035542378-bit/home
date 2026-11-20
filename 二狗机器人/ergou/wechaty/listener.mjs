// A Wechaty 1.x host installs this plugin with bot.use(groupListener(options)).
import { setTimeout as delay } from 'node:timers/promises'

function validId(value) {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= 160
}

export function groupListener({ account, group, secret, port = 8765, warn = console.warn }) {
  if (!validId(account) || !validId(group) || typeof secret !== 'string' || secret.length < 32) {
    throw new Error('需要稳定的账号 ID、群 ID 和至少 32 字符的本机节点密钥')
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('端口无效')

  return bot => {
    let active = true
    let generation = 0
    let verifiedUntil = 0
    let pending = 0
    let delivery = Promise.resolve()
    let heartbeat
    const controller = new AbortController()

    async function post(route, body) {
      const response = await fetch('http://127.0.0.1:' + port + '/bridge/' + route, {
        method: 'POST', redirect: 'error',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + secret },
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error('HTTP ' + response.status)
      return response.json()
    }

    function identity() {
      return bot.isLoggedIn ? bot.currentUser.id : ''
    }

    async function refresh() {
      const session = generation
      const actual = identity()
      let state = actual ? 'NEED_USER_ACTION' : 'WAITING_LOGIN'
      if (actual === account) {
        const room = await bot.Room.find({ id: group })
        if (room?.id === group && await room.has(bot.currentUser)) state = 'LISTENING'
      }
      if (!active || session !== generation || identity() !== actual) return
      const result = await post('heartbeat', {
        adapter_version: 'ergou-wechaty-listener/1', actual_account: actual, state,
        groups: state === 'LISTENING' ? [group] : [],
        capabilities: { receive: true, send: false, stable_ids: true },
      })
      if (session === generation && active) {
        verifiedUntil = result.state === 'LISTENING' ? Date.now() + 15000 : 0
      }
    }

    function sync() {
      heartbeat ??= refresh().catch(() => {
        verifiedUntil = 0
        if (active) warn('二狗监听心跳失败，请检查节点登记、群成员关系和本机服务')
      }).finally(() => { heartbeat = undefined })
      return heartbeat
    }

    function sessionChanged() {
      generation++
      verifiedUntil = 0
      if (heartbeat) heartbeat.then(() => { if (active) void sync() })
      else void sync()
    }

    async function deliver(event, session) {
      for (let attempt = 0; attempt < 3; attempt++) {
        if (!active || session !== generation || identity() !== account) return
        if (Date.now() >= verifiedUntil) await sync()
        try {
          if (!active || session !== generation || identity() !== account) return
          if (Date.now() >= verifiedUntil) throw new Error('未验证监听会话')
          const result = await post('event', event)
          if (!Number.isSafeInteger(result.ingest_sequence)) throw new Error('缺少持久化回执')
          return
        } catch {
          verifiedUntil = 0
          if (attempt < 2 && active) await delay(250 * (attempt + 1))
        }
      }
      if (active) warn('二狗有一条群消息未获得持久化回执，请检查本机桥接服务')
    }

    function onMessage(message) {
      if (!active || identity() !== account || message.room()?.id !== group || message.self()) return
      if (message.type() !== bot.Message.Type.Text) return
      const sender = message.talker()?.id
      if (sender === account) return
      if (!validId(sender) || !validId(message.id)) { warn('二狗忽略缺少稳定标识的群消息'); return }
      const payload = { text: message.text() }
      if (typeof payload.text === 'string' && !payload.text.startsWith('二狗')) return
      if (pending >= 512) { warn('二狗监听队列已满，一条消息未入队'); return }
      if (typeof payload.text !== 'string' || Buffer.byteLength(JSON.stringify(payload)) > 8192) {
        warn('二狗忽略格式或长度超出接入协议的文本')
        return
      }
      const event = { group_id: group, sender_id: sender, source_message_id: message.id, payload }
      const session = generation
      pending++
      delivery = delivery.then(() => deliver(event, session)).catch(() => {
        if (active) warn('二狗群消息回调处理失败')
      }).finally(() => { pending-- })
    }

    bot.on('message', onMessage)
    bot.on('login', sessionChanged)
    bot.on('logout', sessionChanged)
    bot.on('ready', sync)
    const timer = setInterval(sync, 10000)
    timer.unref()
    return () => {
      active = false
      controller.abort()
      clearInterval(timer)
      bot.off('message', onMessage)
      bot.off('login', sessionChanged)
      bot.off('logout', sessionChanged)
      bot.off('ready', sync)
    }
  }
}
