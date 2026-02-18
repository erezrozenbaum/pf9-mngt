import { useState, useEffect, useCallback, useMemo } from "react";
import { API_BASE } from "../config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NavItemDef {
  id: number;
  key: string;
  label: string;
  icon?: string;
  route: string;
  resource_key?: string;
  is_action?: boolean;
  sort_order: number;
}

export interface NavGroupDef {
  id: number;
  key: string;
  label: string;
  icon?: string;
  sort_order: number;
  is_default?: boolean;
  items: NavItemDef[];
}

export interface PermissionEntry {
  resource: string;
  action: string;
}

export interface NavigationData {
  user: {
    username: string;
    role: string;
    department_id: number | null;
    department_name: string | null;
  };
  nav: NavGroupDef[];
  permissions: PermissionEntry[];
}

/** Per-user custom order stored in localStorage / backend preferences */
interface NavCustomOrder {
  groupOrder: string[];                      // group keys in custom order
  itemOrder: Record<string, string[]>;       // groupKey -> item keys in custom order
}

const NAV_ORDER_KEY = "pf9_nav_order";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Apply custom ordering to groups and items, keeping any new/removed items in sync */
function applyCustomOrder(
  serverNav: NavGroupDef[],
  custom: NavCustomOrder | null
): NavGroupDef[] {
  if (!custom) return serverNav;

  // Reorder groups
  const groupMap = new Map(serverNav.map((g) => [g.key, g]));
  const orderedGroups: NavGroupDef[] = [];

  // Custom-ordered groups first
  for (const key of custom.groupOrder) {
    const g = groupMap.get(key);
    if (g) {
      orderedGroups.push(g);
      groupMap.delete(key);
    }
  }
  // Then any new groups the server added that aren't in custom order
  for (const g of groupMap.values()) {
    orderedGroups.push(g);
  }

  // Reorder items within each group
  return orderedGroups.map((group) => {
    const customItemKeys = custom.itemOrder[group.key];
    if (!customItemKeys) return group;

    const itemMap = new Map(group.items.map((i) => [i.key, i]));
    const orderedItems: NavItemDef[] = [];
    for (const key of customItemKeys) {
      const item = itemMap.get(key);
      if (item) {
        orderedItems.push(item);
        itemMap.delete(key);
      }
    }
    for (const item of itemMap.values()) {
      orderedItems.push(item);
    }
    return { ...group, items: orderedItems };
  });
}

/** Find the group that contains a given item key */
function findGroupForItem(nav: NavGroupDef[], itemKey: string): string | null {
  for (const g of nav) {
    if (g.items.some((i) => i.key === itemKey)) return g.key;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useNavigation(isAuthenticated: boolean) {
  const [rawNavData, setRawNavData] = useState<NavigationData | null>(null);
  const [navLoading, setNavLoading] = useState(false);
  const [navError, setNavError] = useState<string | null>(null);
  const [activeGroupKey, setActiveGroupKey] = useState<string | null>(null);

  // Per-user custom order
  const [customOrder, setCustomOrder] = useState<NavCustomOrder | null>(() => {
    try {
      const saved = localStorage.getItem(NAV_ORDER_KEY);
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  // Apply custom order to raw server data
  const navData = useMemo<NavigationData | null>(() => {
    if (!rawNavData) return null;
    return { ...rawNavData, nav: applyCustomOrder(rawNavData.nav, customOrder) };
  }, [rawNavData, customOrder]);

  // ── Persist custom order ──
  const persistOrder = useCallback((order: NavCustomOrder) => {
    localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order));
    // Also save to backend (fire-and-forget)
    const token = localStorage.getItem("auth_token");
    if (token) {
      fetch(`${API_BASE}/user/preferences/nav_order`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ value: order }),
      }).catch(() => {});
    }
  }, []);

  // ── Reorder groups ──
  const reorderGroups = useCallback(
    (fromKey: string, toKey: string) => {
      if (!navData) return;
      const currentKeys = navData.nav.map((g: NavGroupDef) => g.key);
      const fromIdx = currentKeys.indexOf(fromKey);
      const toIdx = currentKeys.indexOf(toKey);
      if (fromIdx === -1 || toIdx === -1) return;
      currentKeys.splice(fromIdx, 1);
      currentKeys.splice(toIdx, 0, fromKey);

      const newOrder: NavCustomOrder = {
        groupOrder: currentKeys,
        itemOrder: customOrder?.itemOrder ?? {},
      };
      setCustomOrder(newOrder);
      persistOrder(newOrder);
    },
    [navData, customOrder, persistOrder]
  );

  // ── Reorder items within a group ──
  const reorderItems = useCallback(
    (groupKey: string, fromKey: string, toKey: string) => {
      if (!navData) return;
      const group = navData.nav.find((g: NavGroupDef) => g.key === groupKey);
      if (!group) return;
      const itemKeys = group.items.map((i: NavItemDef) => i.key);
      const fromIdx = itemKeys.indexOf(fromKey);
      const toIdx = itemKeys.indexOf(toKey);
      if (fromIdx === -1 || toIdx === -1) return;
      itemKeys.splice(fromIdx, 1);
      itemKeys.splice(toIdx, 0, fromKey);

      const newOrder: NavCustomOrder = {
        groupOrder: customOrder?.groupOrder ?? navData.nav.map((g: NavGroupDef) => g.key),
        itemOrder: { ...(customOrder?.itemOrder ?? {}), [groupKey]: itemKeys },
      };
      setCustomOrder(newOrder);
      persistOrder(newOrder);
    },
    [navData, customOrder, persistOrder]
  );

  // ── Reset to default server order ──
  const resetOrder = useCallback(() => {
    setCustomOrder(null);
    localStorage.removeItem(NAV_ORDER_KEY);
    const token = localStorage.getItem("auth_token");
    if (token) {
      fetch(`${API_BASE}/user/preferences/nav_order`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ value: null }),
      }).catch(() => {});
    }
  }, []);

  // ── Fetch navigation from server ──
  const fetchNavigation = useCallback(async () => {
    const token = localStorage.getItem("auth_token");
    if (!token) return;
    setNavLoading(true);
    setNavError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/me/navigation`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (res.status === 404) {
          setRawNavData(null);
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const data: NavigationData = await res.json();
      setRawNavData(data);

      // Auto-select the default group, or first group
      if (!activeGroupKey && data.nav.length > 0) {
        const defaultGroup = data.nav.find((g: NavGroupDef) => g.is_default);
        if (defaultGroup) {
          setActiveGroupKey(defaultGroup.key);
        } else {
          // Fallback: find group containing "dashboard", or first group
          const dashGroup = findGroupForItem(data.nav, "dashboard");
          setActiveGroupKey(dashGroup ?? data.nav[0].key);
        }
      }
    } catch (e: any) {
      console.warn("Failed to fetch navigation:", e);
      setNavError(e.message);
      setRawNavData(null);
    } finally {
      setNavLoading(false);
    }
  }, [activeGroupKey]);

  // ── Load custom order from backend on login ──
  useEffect(() => {
    if (!isAuthenticated) return;
    const token = localStorage.getItem("auth_token");
    if (!token) return;
    fetch(`${API_BASE}/user/preferences`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((prefs: Record<string, any>) => {
        if (prefs.nav_order && typeof prefs.nav_order === "object" && prefs.nav_order.groupOrder) {
          setCustomOrder(prefs.nav_order as NavCustomOrder);
          localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(prefs.nav_order));
        }
      })
      .catch(() => {});
  }, [isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchNavigation();
    } else {
      setRawNavData(null);
      setActiveGroupKey(null);
    }
  }, [isAuthenticated]); // eslint-disable-line react-hooks/exhaustive-deps

  // Active group object
  const activeGroup = useMemo(() => {
    if (!navData) return null;
    return navData.nav.find((g: NavGroupDef) => g.key === activeGroupKey) ?? null;
  }, [navData, activeGroupKey]);

  // All visible tab keys (flat set for quick lookup)
  const visibleTabKeys = useMemo(() => {
    if (!navData) return new Set<string>();
    const keys = new Set<string>();
    for (const g of navData.nav) {
      for (const item of g.items) {
        keys.add(item.key);
      }
    }
    return keys;
  }, [navData]);

  // Permission checker
  const hasPermission = useCallback(
    (resource: string, action: string): boolean => {
      if (!navData) return false;
      return navData.permissions.some(
        (p: PermissionEntry) =>
          (p.resource === resource || p.resource === "*") &&
          (p.action === action || p.action === "admin")
      );
    },
    [navData]
  );

  // Check if a specific tab key is visible
  const isTabVisible = useCallback(
    (tabKey: string): boolean => visibleTabKeys.has(tabKey),
    [visibleTabKeys]
  );

  return {
    navData,
    navLoading,
    navError,
    activeGroupKey,
    setActiveGroupKey,
    activeGroup,
    visibleTabKeys,
    hasPermission,
    isTabVisible,
    refreshNavigation: fetchNavigation,
    // Drag-and-drop reorder
    reorderGroups,
    reorderItems,
    resetOrder,
  };
}
