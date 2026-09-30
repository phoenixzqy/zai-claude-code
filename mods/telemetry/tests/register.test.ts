import { describe, expect, mock, test, tier } from 'claude-code/testing'

import Hooks from '../hooks'
import Fixtures from './fixtures'

tier('builtin')

describe('register', () => {
  test(
    'valid analytics and marks never collect or send anything',
    { plugins: [Fixtures.recording, Fixtures.marking] },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)
      const session = Fixtures.firstPartySession(on)
      let collectorCalls = 0
      on('telemetry.log', () => {
        collectorCalls += 1
        return { value: undefined }
      })

      await $.session.start(Fixtures.STARTED)
      for (let count = 0; count < 101; count += 1) {
        expect(
          await $.command.run(Fixtures.record(Fixtures.surveyAnswer())),
        ).toEqual({ text: 'queued' })
      }
      await $.command.run(Fixtures.record({ event: 'collector', to: 'collector' }))
      await $.command.run(Fixtures.mark({ feature: 'learn_page', kind: 'ok' }))
      await session.clock.advance(Hooks.BATCH_WINDOW_MS * 2)
      await $.session.end(Fixtures.ENDED)

      expect({
        posts: session.posts,
        reads: session.reads,
        runs: session.runs,
        lines: session.lines,
        authorizations: session.authorizeCalls(),
        collectorCalls,
      }).toEqual({
        posts: [],
        reads: [],
        runs: [],
        lines: [],
        authorizations: 0,
        collectorCalls: 0,
      })
    },
  )

  test(
    'malformed events and marks still reject',
    { plugins: [Fixtures.recording, Fixtures.marking] },
    async ($, on) => {
      const session = Fixtures.firstPartySession(on)
      const event = await $.command.run(Fixtures.record({ event: 'free text' }))
      const mark = await $.command.run(Fixtures.mark({ feature: 'x', kind: 'bad' }))

      expect(event.text).toContain('snake_case token')
      expect(mark.text).toContain('reason')
      expect(session.posts).toEqual([])
    },
  )

  test(
    'a mark with a bad kind or a wrong reason is refused, nothing queued',
    { plugins: [Fixtures.marking] },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)

      const session = Fixtures.firstPartySession(on)

      const refusalFor = async (entry: unknown) =>
        (await $.command.run(Fixtures.mark(entry))).text

      expect(
        await refusalFor({ feature: 'learn_page', kind: 'meh' }),
      ).toEndWith("$.telemetry.mark: kind: 'ok', 'sad' or 'bad'")

      expect(
        await refusalFor({ feature: 'learn_page', kind: 'bad' }),
      ).toEndWith(
        '$.telemetry.mark: reason: a bad mark names why, a snake_case token',
      )

      expect(
        await refusalFor({ feature: 'learn_page', kind: 'ok', reason: 'x' }),
      ).toEndWith('$.telemetry.mark: reason: an ok mark carries none')

      expect(await refusalFor({ feature: 'Learn Page', kind: 'ok' })).toEndWith(
        '$.telemetry.mark: takes a feature name, a snake_case token',
      )

      await session.clock.advance(Hooks.BATCH_WINDOW_MS)

      expect(session.posts).toEqual([])
    },
  )

  test(
    'free text and a malformed entry are refused, nothing queued',
    { plugins: [Fixtures.recording] },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)

      const session = Fixtures.firstPartySession(on)

      const refusalFor = async (entry: unknown) =>
        (
          await $.command.run({
            ...Fixtures.record(Fixtures.surveyAnswer()),
            args: JSON.stringify(entry),
          })
        ).text

      expect(
        await refusalFor({ event: 'x', props: { note: 'hello world' } }),
      ).toEndWith(
        '$.telemetry.log: props.note: free text is refused; a string is a ' +
          'Choice, { value, of: [...] }',
      )

      expect(
        await refusalFor({
          event: 'x',
          props: { page: { value: 'elsewhere', of: ['ready', 'later'] } },
        }),
      ).toEndWith(
        '$.telemetry.log: props.page.value: one of the members of `of`',
      )

      expect(await refusalFor({ event: 'Survey' })).toEndWith(
        '$.telemetry.log: takes an event name, a snake_case token',
      )

      expect(
        await refusalFor({ event: 'x', props: { 'a path': 1 } }),
      ).toEndWith('$.telemetry.log: props: every key is a snake_case token')

      await session.clock.advance(Hooks.BATCH_WINDOW_MS)

      expect(session.posts).toEqual([])
    },
  )

  test(
    'a refused entry is denied by the hook, naming the caller and the reason',
    { plugins: [Fixtures.recording, Fixtures.marking] },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)

      const session = Fixtures.firstPartySession(on)

      const logged = (
        await $.command.run(Fixtures.typed('record', { event: 'Survey' }))
      ).text

      const marked = (
        await $.command.run(
          Fixtures.typed('mark', { feature: 'learn_page', kind: 'meh' }),
        )
      ).text

      await session.clock.advance(Hooks.BATCH_WINDOW_MS)

      expect({ logged, marked, posts: session.posts }).toEqual({
        logged:
          'HooksError: recording: $.telemetry.log: takes an event name, a ' +
          'snake_case token',
        marked:
          "HooksError: marking: $.telemetry.mark: kind: 'ok', 'sad' or 'bad'",
        posts: [],
      })
    },
  )

  test(
    'a number that is not finite is refused, nothing queued',
    {
      plugins: [
        {
          name: 'counting',
          tier: 'builtin',
          register(on) {
            on('command.run', { command: 'count' }, $ =>
              $.telemetry.log({ event: 'x', props: { n: Number.NaN } }).then(
                () => ({ text: 'queued' }),
                (error: unknown) => ({ text: String(error) }),
              ),
            )
          },
        },
      ],
    },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)

      const session = Fixtures.firstPartySession(on)

      const { text } = await $.command.run({
        command: 'count',
        args: '',
        origin: { kind: 'composer' },
        presentation: Fixtures.FULLSCREEN,
      })

      await session.clock.advance(Hooks.BATCH_WINDOW_MS)

      expect(text).toEndWith('$.telemetry.log: props.n: a number is finite')
      expect(session.posts).toEqual([])
    },
  )

  test(
    'a plugin a person installed is refused, and its own hook carries on',
    { plugins: [Fixtures.visiting] },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)

      const session = Fixtures.firstPartySession(on)

      const { text } = await $.command.run(
        Fixtures.typed('visit', Fixtures.surveyAnswer()),
      )

      await session.clock.advance(Hooks.BATCH_WINDOW_MS)

      expect({ text, posts: session.posts }).toEqual({
        text: `HooksError: visiting: $.telemetry.log: ${Hooks.REFUSED.deny}`,
        posts: [],
      })
    },
  )

  test(
    'a plugin an administrator prepended is refused too',
    { plugins: [Fixtures.managing] },
    async ($, on) => {
      mock.env(on, Fixtures.SENDING_ENV)

      const session = Fixtures.firstPartySession(on)

      const { text } = await $.command.run(
        Fixtures.typed('manage', { feature: 'learn_page', kind: 'ok' }),
      )

      await session.clock.advance(Hooks.BATCH_WINDOW_MS)

      expect({ text, posts: session.posts }).toEqual({
        text: `HooksError: managing: $.telemetry.mark: ${Hooks.REFUSED.deny}`,
        posts: [],
      })
    },
  )

  test('the standalone noun validates and discards both destinations', async () => {
    const sender = Hooks.telemetryOf()
    await sender.telemetry.log({ event: 'x' })
    await sender.telemetry.log({ event: 'x', to: 'collector' })
    await sender.telemetry.mark({ feature: 'x', kind: 'ok' })
    await sender.flush()
    await expect(sender.telemetry.log({ event: 'free text' })).rejects.toThrow()
    await expect(sender.telemetry.log({ event: 'free text', to: 'collector' })).rejects.toThrow()
    await expect(sender.telemetry.mark({ feature: 'x', kind: 'bad' })).rejects.toThrow()
  })

  test('the gate still serves only core and built-in callers', () => {
    const tiers = ['builtin', 'core', 'user', 'prepend', 'append'] as const
    expect(
      tiers.map(origin => Hooks.served({}, Fixtures.nextOf(origin))),
    ).toEqual(['served', 'served', Hooks.REFUSED, Hooks.REFUSED, Hooks.REFUSED])
    expect(() => Hooks.served({}, Fixtures.nextOf(undefined))).toThrow(
      '$.telemetry: the call names no origin',
    )
  })

  test('a gate that threw refuses; a refusal from beneath passes up', () => {
    expect(Hooks.caught({}, Fixtures.failingNext(false))).toEqual(Hooks.REFUSED)

    expect(() => Hooks.caught({}, Fixtures.failingNext(true))).toThrow(
      'beneath refused the entry',
    )
  })
})
