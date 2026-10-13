/**
 * Read the device-location context.
 *
 * Returns `null` when there is no provider above the caller, rather than
 * throwing: a component that renders outside the provider (a test, an isolated
 * story) should degrade to "no location known" and keep working, exactly as it
 * did before this feature existed. Callers guard with `?.` for that reason.
 */
import { useContext } from 'react'

import DeviceLocationContext from '@/context/deviceLocationContextObject'

export default function useDeviceLocation() {
  return useContext(DeviceLocationContext)
}
