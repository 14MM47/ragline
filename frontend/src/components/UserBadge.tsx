// UserBadge — who is signed in, and the way out.
//
// Reads GET /api/auth/me once on mount. With AUTH_ENABLED=false (local dev)
// the backend reports auth_enabled: false and the badge renders nothing —
// the header stays exactly as it was before auth existed.

import { useEffect, useState } from 'react'
import { getMe, logout, type Me } from '../api'

export default function UserBadge() {
  const [me, setMe] = useState<Me | null>(null)

  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => setMe(null)) // header must never break on an identity hiccup
  }, [])

  if (!me || !me.auth_enabled) return null

  const label = me.display_name || me.upn || 'Signed in'

  return (
    <div className="flex items-center gap-2 pl-2 ml-1 border-l border-theme-main">
      <span
        className="text-xs text-theme-secondary max-w-[160px] truncate"
        title={me.upn}
      >
        {label}
      </span>
      {/* POST first (the server clears the cookie), THEN navigate wherever
          it says — "/" or the Entra end-session page. A plain <a href> would
          be a GET, which the server no longer accepts (CSRF hardening). */}
      <button
        onClick={() => {
          logout().then((url) => {
            window.location.href = url
          })
        }}
        className="text-xs text-theme-tertiary hover:text-[var(--accent)] transition-colors"
        title="Sign out"
      >
        Sign out
      </button>
    </div>
  )
}
