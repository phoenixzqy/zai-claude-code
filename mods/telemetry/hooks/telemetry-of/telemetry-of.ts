import Entries from '../entries'
import type { Sender } from '../sender'

export function telemetryOf(): Sender {
  return {
    telemetry: {
      log: async entry => {
        Entries.checkedFields(entry)
      },
      mark: async entry => {
        Entries.checkedMark(entry)
      },
    },
    flush: async () => {},
  }
}
