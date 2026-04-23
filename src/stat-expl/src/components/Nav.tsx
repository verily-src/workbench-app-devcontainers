import { Link, useLocation } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/passport', label: 'Passport' },
  { path: '/population', label: 'Population' },
  { path: '/variables', label: 'Variables' },
  { path: '/quality', label: 'Quality' },
  { path: '/hypotheses', label: 'Hypotheses' }
];

export function Nav() {
  const location = useLocation();

  return (
    <nav className="bg-slate-800 text-white">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center space-x-8">
            <h1 className="text-xl font-semibold">Dataset Statistical Explorer</h1>
            <div className="flex space-x-1">
              {NAV_ITEMS.map(item => {
                const isActive = location.pathname === item.path;
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`px-4 py-2 rounded transition-colors ${
                      isActive
                        ? 'bg-slate-700 text-white'
                        : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
          <button
            className="px-4 py-2 bg-teal-600 hover:bg-teal-700 rounded text-white transition-colors"
            onClick={() => console.log('Export clicked')}
          >
            Export Report
          </button>
        </div>
      </div>
    </nav>
  );
}
