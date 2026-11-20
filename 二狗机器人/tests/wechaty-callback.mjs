import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { groupListener } from '../ergou/wechaty/listener.mjs'

// Python runs the real HTTP server. Lose its first successful acknowledgement
// so the plugin must replay the same source ID over a second HTTP connection.
const [port, group, account] = process.argv.slice(2)
const originalFetch = globalThis.fetch
const acks = []
const received = Promise.withResolvers()
globalThis.fetch = async (url, options) => {
  const response = await originalFetch(url, options)
  if (url.endsWith('/event') && response.ok) {
    acks.push((await response.clone().json()).ingest_sequence)
    if (acks.length === 1) throw new Error('lost acknowledgement')
    if (acks.length === 3) received.resolve()
  }
  return response
}
const bot = new EventEmitter()
const room = { id: group, has: async user => user.id === account }
Object.assign(bot, {
  isLoggedIn: true, currentUser: { id: account }, Message: { Type: { Text: 7 } },
  Room: { find: async ({ id }) => id === group ? room : null },
})
const warnings = []
const uninstall = groupListener({
  account, group, port: Number(port), secret: process.env.ERGOU_NODE_SECRET,
  warn: text => warnings.push(text),
})(bot)
const message = {
  id: 'message-100', self: () => false, type: () => 7, room: () => room,
  talker: () => ({ id: 'member-200' }), text: () => '二狗 开始 成语接龙',
}
function excluded(overrides) {
  bot.emit('message', { ...message, text: () => assert.fail('读取了排除事件的正文'), ...overrides })
}
excluded({ room: () => undefined })
excluded({ room: () => ({ id: 'another-room' }) })
excluded({ self: () => true })
excluded({ type: () => 1 })
excluded({ id: '' })
bot.currentUser.id = 'another-account'
excluded({})
bot.currentUser.id = account
bot.emit('message', message)
bot.emit('message', { ...message, id: 'ignored', text: () => '普通群消息' })
bot.emit('message', { ...message, id: 'message-101', text: () => '二狗积分' })
const deadline = setTimeout(() => received.reject(new Error('missing callback acknowledgement')), 12000)
try {
  await received.promise
  assert.equal(acks[0], acks[1])
  assert.ok(acks[2] > acks[1])
  assert.equal(warnings.length, 1)
} finally {
  clearTimeout(deadline)
  uninstall()
}
assert.equal(bot.listenerCount('message'), 0)
