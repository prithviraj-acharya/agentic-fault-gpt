import { NavLink } from 'react-router-dom'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }: { isActive: boolean }) =>
        [
          'block rounded-md px-3 py-2 text-sm font-medium',
          isActive ? 'bg-slate-200 text-slate-900' : 'text-slate-700 hover:bg-slate-100',
        ].join(' ')
      }
    >
      {label}
    </NavLink>
  )
}

export function Sidebar() {
  return (
    <aside className="w-64 shrink-0 border-r border-slate-200 bg-white min-h-screen sticky top-0">
      <div className="px-4 py-5">
        <div className="text-lg font-semibold">BMS Agent</div>
      </div>
      <nav className="px-3 space-y-1">
        <NavItem to="/live" label="Live Monitoring" />
        <NavItem to="/windows" label="Window Analysis" />
      </nav>
    </aside>
  )
}
