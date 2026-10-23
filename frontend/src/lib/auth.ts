import { createContext, useContext } from 'react'

/** Who is signed in. accounts=false: no sign-in on this server (laptop, public demo); everyone is the owner. */
export interface Me { accounts: boolean; signed_in: boolean; name: string | null; role: 'owner' | 'member' | null; seats_left: number }

export const AuthContext = createContext<Me | null>(null)

/** True for a friend's account: they can view the bot but not change it. */
export function useReadOnly(): boolean {
  return useContext(AuthContext)?.role === 'member'
}

export function useMe(): Me | null {
  return useContext(AuthContext)
}
