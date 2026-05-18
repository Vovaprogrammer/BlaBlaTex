import React, { useState, useRef, useEffect } from "react";
import { User, LogOut, Settings, ChevronDown } from "lucide-react";

interface UserMenuProps {
  onLogout?: () => void;
  username?: string;
}

export const UserMenu: React.FC<UserMenuProps> = ({ onLogout, username }) => {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const handleLogout = () => {
    localStorage.removeItem("supabase_uid");
    localStorage.removeItem("access_token");
    window.location.href = "/";
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium text-white/90 hover:text-white hover:bg-white/15 rounded-md transition-all"
      >
        <div className="w-7 h-7 bg-blue-300 dark:bg-white/20 rounded-full flex items-center justify-center">
          <User className="w-4 h-4 text-white dark:text-white" />
        </div>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 overflow-hidden z-50">
          {/* User info */}
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
              {username || "User"}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
              Signed in
            </p>
          </div>

          {/* Menu items */}
          <div className="py-1">
            <button
              className="flex items-center w-full px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors gap-3"
              onClick={() => setOpen(false)}
            >
              <User className="w-4 h-4 text-gray-400" />
              Profile
            </button>
            <button
              className="flex items-center w-full px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors gap-3"
              onClick={() => setOpen(false)}
            >
              <Settings className="w-4 h-4 text-gray-400" />
              Settings
            </button>
          </div>

          {/* Logout */}
          <div className="border-t border-gray-100 dark:border-gray-700 py-1">
            <button
              className="flex items-center w-full px-4 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors gap-3"
              onClick={handleLogout}
            >
              <LogOut className="w-4 h-4" />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
};