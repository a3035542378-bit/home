import { once } from 'node:events'
import { createRequire } from 'node:module'
import path from 'node:path'
import { groupListener } from '../ergou/wechaty/listener.mjs'

const [port] = process.argv.slice(2)
const require = createRequire(path.join(process.env.ERGOU_SDK_HOST, 'package.json'))
const { WechatyBuilder } = require('wechaty')
const { mock, PuppetMock } = require('wechaty-puppet-mock')
const mocker = new mock.Mocker()
const user = mocker.createContact({ id: 'sdk-account' })
const member = mocker.createContact({ id: 'sdk-member' })
const room = mocker.createRoom({ id: 'sdk-room', memberIdList: [member.id, user.id] })
// Upstream PuppetMock 1.18.2 returns [] unconditionally for roomMemberList.
// Supply the members created in this fixture so the production guard is exercised.
class FixturePuppet extends PuppetMock {
  async roomMemberList(id) { return (await this.roomPayload(id)).memberIdList }
}
const bot = WechatyBuilder.build({ puppet: new FixturePuppet({ mocker }) })
const received = Promise.withResolvers()
const nativeFetch = globalThis.fetch
globalThis.fetch = async (url, opts) => {
  const response = await nativeFetch(url, opts)
  if (!response.ok || (url.endsWith('/heartbeat') && JSON.parse(opts.body).state !== 'LISTENING')) {
    console.error('SDK fixture bridge response', url, await response.clone().text())
  }
  if (response.ok && url.endsWith('/event')) {
    received.resolve(JSON.parse(opts.body).source_message_id)
  }
  return response
}
bot.use(groupListener({ account: user.id, group: room.id, port: Number(port),
  secret: process.env.ERGOU_NODE_SECRET }))
const timer = setTimeout(() => received.reject(new Error('SDK callback timeout')), 15000)
try {
  await bot.start()
  const login = once(bot, 'login')
  mocker.login(user)
  await login
  member.say('二狗 开始 成语接龙').to(room)
  console.log('SOURCE=' + await received.promise)
} finally {
  clearTimeout(timer)
  await bot.stop()
}
