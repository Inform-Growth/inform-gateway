import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

const TITLES: Record<string, string> = {
  '/dashboard':  'Dashboard',
  '/tool-calls': 'Tool Calls',
  '/tasks':      'Tasks',
  '/operators':  'Operators',
  '/tools':      'Tools',
  '/skills':     'Skills',
  '/tool-hints': 'Tool Hints',
  '/settings':   'Settings',
};

export function AppShell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? 'Gateway';
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <TopBar title={title} />
        <main className="flex-1 overflow-y-auto px-6 pb-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
