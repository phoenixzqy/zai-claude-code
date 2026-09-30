import type { EngineInterface, On } from 'claude-code'

import { answerOf } from './answer-of'
import Gate from './gate'
import { telemetryOf } from './telemetry-of'

export function register(on: On) {
  const sender = telemetryOf()

  on('telemetry.*', (_$, e, next) => Gate.served(e, next)).catch(
    (_$, e, next) => Gate.caught(e, next),
  )

  on('telemetry.log', (_$, e) => answerOf(sender.telemetry.log(e)))
  on('telemetry.mark', (_$, e) => answerOf(sender.telemetry.mark(e)))

  on('engine.create', async (_$, e, next) => {
    const beneath = await next(e)
    const telemetry: EngineInterface['telemetry'] = sender.telemetry
    const added = { telemetry }

    return { ...added, ...beneath }
  })
}
