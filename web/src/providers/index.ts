import type { AppProvider } from './contracts'
import { LiveApiProvider } from './live'

export function createProvider(): AppProvider {
  return new LiveApiProvider()
}

export type { AppProvider }
