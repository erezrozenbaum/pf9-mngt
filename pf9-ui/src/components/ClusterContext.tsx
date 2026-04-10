/**
 * ClusterContext.tsx — Global React context for multi-region support.
 *
 * Provides the selected region filter to all child components so they can
 * append ?region_id= to their API calls without prop-drilling.
 *
 * Only fetches region data for superadmin users (the cluster admin API
 * requires superadmin). For all other roles the context is a no-op:
 * selectedRegionId stays null, regionParam() returns "".
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { API_BASE } from "../config";
import { getToken } from '../lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ControlPlane {
  id: string;
  name: string;
  auth_url: string;
  display_color?: string | null;
  is_enabled?: boolean;
  is_default?: boolean;
  region_count?: number;
}

export interface Region {
  id: string;
  control_plane_id: string;
  region_name: string;
  display_name: string;
  is_default?: boolean;
  is_enabled?: boolean;
  health_status?: string | null;
  priority?: number;
  last_sync_at?: string | null;
}

interface ClusterContextValue {
  controlPlanes: ControlPlane[];
  regions: Region[];
  selectedRegionId: string | null;
  setSelectedRegionId: (id: string | null) => void;
  /** Returns "region_id=xxx" or "" — safe to append to existing query strings with & */
  regionParam: () => string;
  reload: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const defaultValue: ClusterContextValue = {
  controlPlanes: [],
  regions: [],
  selectedRegionId: null,
  setSelectedRegionId: () => {},
  regionParam: () => "",
  reload: () => {},
};

const ClusterContext = createContext<ClusterContextValue>(defaultValue);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface ProviderProps {
  children: React.ReactNode;
  userRole: string;
}

export function ClusterContextProvider({ children, userRole }: ProviderProps) {
  const [controlPlanes, setControlPlanes] = useState<ControlPlane[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);

  const loadRegions = useCallback(async () => {
    if (userRole !== "superadmin") return;
    const token = getToken();
    if (!token) return;
    try {
      const cpsRes = await fetch(`${API_BASE}/admin/control-planes`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!cpsRes.ok) return;
      const cps: ControlPlane[] = await cpsRes.json();
      setControlPlanes(cps);

      const all: Region[] = [];
      for (const cp of cps) {
        if (!cp.is_enabled) continue;
        const rRes = await fetch(
          `${API_BASE}/admin/control-planes/${encodeURIComponent(cp.id)}/regions`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (!rRes.ok) continue;
        const rData: Region[] = await rRes.json();
        all.push(...rData.filter((r) => r.is_enabled));
      }
      setRegions(all);
    } catch {
      // Network error or auth failure — feature degrades gracefully.
      // The rest of the app continues to work in single-region mode.
    }
  }, [userRole]);

  useEffect(() => {
    loadRegions();
  }, [loadRegions]);

  const regionParam = useCallback((): string => {
    return selectedRegionId
      ? `region_id=${encodeURIComponent(selectedRegionId)}`
      : "";
  }, [selectedRegionId]);

  return (
    <ClusterContext.Provider
      value={{
        controlPlanes,
        regions,
        selectedRegionId,
        setSelectedRegionId,
        regionParam,
        reload: loadRegions,
      }}
    >
      {children}
    </ClusterContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useClusterContext(): ClusterContextValue {
  return useContext(ClusterContext);
}
