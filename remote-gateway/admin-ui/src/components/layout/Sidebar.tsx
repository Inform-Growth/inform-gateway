import { NavLink } from 'react-router-dom';
import { BRAND_NAME } from '@/lib/branding';
import {
  LayoutDashboard, Activity, ListTodo, Users, Wrench,
  Sparkles, MessageSquareWarning, Settings,
} from 'lucide-react';

type NavItem = { to: string; label: string; icon: React.ComponentType<{ className?: string }> };
type NavGroup = { label?: string; items: NavItem[] };

const groups: NavGroup[] = [
  { items: [{ to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard }] },
  {
    label: 'Activity',
    items: [
      { to: '/tool-calls', label: 'Tool Calls', icon: Activity },
      { to: '/tasks',      label: 'Tasks',      icon: ListTodo },
      { to: '/operators',  label: 'Operators',  icon: Users },
    ],
  },
  {
    label: 'Registry',
    items: [
      { to: '/tools',      label: 'Tools',      icon: Wrench },
      { to: '/skills',     label: 'Skills',     icon: Sparkles },
      { to: '/tool-hints', label: 'Tool Hints', icon: MessageSquareWarning },
    ],
  },
  { items: [{ to: '/settings', label: 'Settings', icon: Settings }] },
];

export function Sidebar() {
  return (
    <aside className="w-60 border-r border-border bg-card flex flex-col">
      <div className="h-14 px-4 flex items-center border-b border-border">
        <span className="font-serif font-bold tracking-widest uppercase text-sm">
          {BRAND_NAME}
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto py-4">
        {groups.map((g, i) => (
          <div key={i} className="mb-4">
            {g.label && (
              <div className="px-4 mb-1 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                {g.label}
              </div>
            )}
            {g.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-4 py-2 text-sm hover:bg-secondary ${
                    isActive ? 'bg-secondary border-l-2 border-accent font-bold' : ''
                  }`
                }
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}
