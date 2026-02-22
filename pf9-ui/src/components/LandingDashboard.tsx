import React, { useEffect, useState, useCallback, useRef } from 'react';
import '../styles/LandingDashboard.css';
import { useTheme } from '../hooks/useTheme';
import { HealthSummaryCard } from './HealthSummaryCard';
import { SnapshotSLAWidget } from './SnapshotSLAWidget';
import { HostUtilizationCard } from './HostUtilizationCard';
import { RecentActivityWidget } from './RecentActivityWidget';
import { CoverageRiskCard } from './CoverageRiskCard';
import { CapacityPressureCard } from './CapacityPressureCard';
import { VMHotspotsCard } from './VMHotspotsCard';
import { ChangeComplianceCard } from './ChangeComplianceCard';
import { TenantRiskScoreCard } from './TenantRiskScoreCard';
import { TrendlinesCard } from './TrendlinesCard';
import { TenantRiskHeatmapCard } from './TenantRiskHeatmapCard';
import { CapacityTrendsCard } from './CapacityTrendsCard';
import { ComplianceDriftCard } from './ComplianceDriftCard';
import { API_BASE } from '../config';

interface DashboardData {
  health: any;
  sla: any;
  hosts: any;
  activity: any;
  coverage: any;
  capacity: any;
  vmHotspotsCpu: any;
  vmHotspotsMemory: any;
  vmHotspotsStorage: any;
  changeCompliance: any;
  tenantRisk: any;
  trendlines: any;
  tenantRiskHeatmap: any;
  capacityTrends: any;
  complianceDrift: any;
}

// ---------- Widget registry for the chooser ----------
type WidgetId =
  | 'health'
  | 'sla'
  | 'coverage'
  | 'hosts'
  | 'activity'
  | 'vmHotspots'
  | 'tenantRisk'
  | 'tenantRiskHeatmap'
  | 'capacity'
  | 'changeCompliance'
  | 'complianceDrift'
  | 'trendlines'
  | 'capacityTrends';

interface WidgetMeta {
  id: WidgetId;
  label: string;
  icon: string;
  description: string;
  defaultVisible: boolean;
}

const WIDGET_REGISTRY: WidgetMeta[] = [
  { id: 'health', label: 'System Health', icon: '📊', description: 'Tenants, VMs, volumes & resource utilization', defaultVisible: true },
  { id: 'sla', label: 'Snapshot SLA', icon: '📸', description: 'Snapshot compliance by tenant', defaultVisible: true },
  { id: 'coverage', label: 'Coverage Risks', icon: '🛡️', description: 'Snapshot coverage gaps & density', defaultVisible: true },
  { id: 'hosts', label: 'Top Hosts', icon: '🖥️', description: 'Host utilization ranked by usage', defaultVisible: true },
  { id: 'activity', label: 'Recent Activity', icon: '🕐', description: 'Latest infrastructure changes', defaultVisible: true },
  { id: 'vmHotspots', label: 'VM Hotspots', icon: '🔥', description: 'Top resource-consuming VMs', defaultVisible: true },
  { id: 'tenantRisk', label: 'Tenant Risk Scores', icon: '⚡', description: 'Risk scores per tenant', defaultVisible: true },
  { id: 'tenantRiskHeatmap', label: 'Risk Heatmap', icon: '🧭', description: 'Visual risk map across tenants', defaultVisible: true },
  { id: 'capacity', label: 'Capacity Pressure', icon: '📈', description: 'Cluster capacity & pressure points', defaultVisible: true },
  { id: 'changeCompliance', label: 'Change & Compliance', icon: '✅', description: 'Recent changes & compliance status', defaultVisible: true },
  { id: 'complianceDrift', label: 'Compliance Drift', icon: '📉', description: 'Drift signals over time', defaultVisible: false },
  { id: 'trendlines', label: 'Trendlines', icon: '📊', description: 'Historical metric trends', defaultVisible: false },
  { id: 'capacityTrends', label: 'Capacity Trends', icon: '📐', description: 'Capacity usage over time', defaultVisible: false },
];

const STORAGE_KEY_WIDGETS = 'pf9_dashboard_widgets';

function loadVisibleWidgets(): Set<WidgetId> {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_WIDGETS);
    if (saved) {
      const arr: WidgetId[] = JSON.parse(saved);
      return new Set(arr);
    }
  } catch { /* ignore */ }
  return new Set(WIDGET_REGISTRY.filter(w => w.defaultVisible).map(w => w.id));
}

function saveVisibleWidgets(set: Set<WidgetId>) {
  localStorage.setItem(STORAGE_KEY_WIDGETS, JSON.stringify([...set]));
}

interface Props {
  onNavigate?: (tab: string) => void;
}

export const LandingDashboard: React.FC<Props> = ({ onNavigate }) => {
  const { theme } = useTheme();
  const [data, setData] = useState<DashboardData>({
    health: null,
    sla: null,
    hosts: null,
    activity: null,
    coverage: null,
    capacity: null,
    vmHotspotsCpu: null,
    vmHotspotsMemory: null,
    vmHotspotsStorage: null,
    changeCompliance: null,
    tenantRisk: null,
    trendlines: null,
    tenantRiskHeatmap: null,
    capacityTrends: null,
    complianceDrift: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [lastRVToolsRun, setLastRVToolsRun] = useState<{last_run: string; source?: string; duration_seconds?: number} | null>(null);

  // Widget chooser state
  const [visibleWidgets, setVisibleWidgets] = useState<Set<WidgetId>>(loadVisibleWidgets);
  const [showWidgetChooser, setShowWidgetChooser] = useState(false);
  const chooserRef = useRef<HTMLDivElement>(null);

  const toggleWidget = useCallback((id: WidgetId) => {
    setVisibleWidgets(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveVisibleWidgets(next);
      return next;
    });
  }, []);

  const resetWidgets = useCallback(() => {
    const defaults = new Set(WIDGET_REGISTRY.filter(w => w.defaultVisible).map(w => w.id));
    setVisibleWidgets(defaults);
    saveVisibleWidgets(defaults);
  }, []);

  // Close chooser on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (chooserRef.current && !chooserRef.current.contains(e.target as Node)) {
        setShowWidgetChooser(false);
      }
    };
    if (showWidgetChooser) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showWidgetChooser]);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      setError(null);

      const token = localStorage.getItem('auth_token');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
      };

      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      // Fetch all dashboard data in parallel
      const [
        healthRes,
        slaRes,
        hostsRes,
        activityRes,
        coverageRes,
        capacityRes,
        vmCpuRes,
        vmMemRes,
        vmStorageRes,
        changeComplianceRes,
        tenantRiskRes,
        trendlinesRes,
        tenantRiskHeatmapRes,
        capacityTrendsRes,
        complianceDriftRes,
        rvtoolsRes
      ] = await Promise.all([
        fetch(`${API_BASE}/dashboard/health-summary`, { headers }),
        fetch(`${API_BASE}/dashboard/snapshot-sla-compliance`, { headers }),
        fetch(`${API_BASE}/dashboard/top-hosts-utilization`, { headers }),
        fetch(`${API_BASE}/dashboard/recent-changes`, { headers }),
        fetch(`${API_BASE}/dashboard/coverage-risks`, { headers }),
        fetch(`${API_BASE}/dashboard/capacity-pressure`, { headers }),
        fetch(`${API_BASE}/dashboard/vm-hotspots?sort=cpu`, { headers }),
        fetch(`${API_BASE}/dashboard/vm-hotspots?sort=memory`, { headers }),
        fetch(`${API_BASE}/dashboard/vm-hotspots?sort=storage`, { headers }),
        fetch(`${API_BASE}/dashboard/change-compliance`, { headers }),
        fetch(`${API_BASE}/dashboard/tenant-risk-scores`, { headers }),
        fetch(`${API_BASE}/dashboard/trendlines`, { headers }),
        fetch(`${API_BASE}/dashboard/tenant-risk-heatmap`, { headers }),
        fetch(`${API_BASE}/dashboard/capacity-trends`, { headers }),
        fetch(`${API_BASE}/dashboard/compliance-drift`, { headers }),
        fetch(`${API_BASE}/dashboard/rvtools-last-run`, { headers }),
      ]);

      // Helper: parse response or return null on failure (graceful degradation)
      const safeJson = async (res: Response) => {
        try { return res.ok ? await res.json() : null; } catch { return null; }
      };

      // If we get a 401, clear the invalid token but don't reload - let the app show login page
      if (
        healthRes.status === 401 ||
        slaRes.status === 401 ||
        hostsRes.status === 401 ||
        activityRes.status === 401 ||
        coverageRes.status === 401 ||
        capacityRes.status === 401 ||
        vmCpuRes.status === 401 ||
        vmMemRes.status === 401 ||
        vmStorageRes.status === 401 ||
        changeComplianceRes.status === 401 ||
        tenantRiskRes.status === 401 ||
        trendlinesRes.status === 401 ||
        tenantRiskHeatmapRes.status === 401 ||
        capacityTrendsRes.status === 401 ||
        complianceDriftRes.status === 401
      ) {
        if (token) {
          localStorage.removeItem('auth_token');
          localStorage.removeItem('auth_user');
          localStorage.removeItem('token_expires_at');
        }
        setError('Authentication required. Please login.');
        return;
      }

      // Gracefully degrade: parse each response individually; null on failure
      const [
        health,
        sla,
        hosts,
        activity,
        coverage,
        capacity,
        vmHotspotsCpu,
        vmHotspotsMemory,
        vmHotspotsStorage,
        changeCompliance,
        tenantRisk,
        trendlines,
        tenantRiskHeatmap,
        capacityTrends,
        complianceDrift,
        rvtoolsLastRun
      ] = await Promise.all([
        safeJson(healthRes),
        safeJson(slaRes),
        safeJson(hostsRes),
        safeJson(activityRes),
        safeJson(coverageRes),
        safeJson(capacityRes),
        safeJson(vmCpuRes),
        safeJson(vmMemRes),
        safeJson(vmStorageRes),
        safeJson(changeComplianceRes),
        safeJson(tenantRiskRes),
        safeJson(trendlinesRes),
        safeJson(tenantRiskHeatmapRes),
        safeJson(capacityTrendsRes),
        safeJson(complianceDriftRes),
        safeJson(rvtoolsRes),
      ]);

      setData({
        health,
        sla,
        hosts,
        activity,
        coverage,
        capacity,
        vmHotspotsCpu,
        vmHotspotsMemory,
        vmHotspotsStorage,
        changeCompliance,
        tenantRisk,
        trendlines,
        tenantRiskHeatmap,
        capacityTrends,
        complianceDrift,
      });
      setLastRefresh(new Date());
      setLastRVToolsRun(rvtoolsLastRun?.last_run ? rvtoolsLastRun : null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load dashboard data'
      );
      console.error('Dashboard error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();

    // Refresh every 60 seconds
    const interval = setInterval(fetchDashboardData, 60000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    fetchDashboardData();
  };

  if (loading && !data.health) {
    return (
      <div className={`landing-dashboard loading ${theme === 'dark' ? 'dark' : ''}`}>
        <div className="spinner">
          <div className="bounce1"></div>
          <div className="bounce2"></div>
          <div className="bounce3"></div>
        </div>
        <p>Loading dashboard...</p>
      </div>
    );
  }

  return (
    <div className={`landing-dashboard ${theme === 'dark' ? 'dark' : ''}`}>
      <div className="dashboard-header">
        <div className="header-content">
          <h1>Operations Dashboard</h1>
          <p className="subtitle">Infrastructure health at a glance</p>
        </div>
        <div className="header-actions">
          <div className="widget-chooser-wrapper" ref={chooserRef}>
            <button
              className="widget-chooser-toggle"
              onClick={() => setShowWidgetChooser(v => !v)}
              title="Customize widgets"
            >
              ⚙ Customize
            </button>
            {showWidgetChooser && (
              <div className="widget-chooser-panel">
                <div className="widget-chooser-header">
                  <span className="widget-chooser-title">Dashboard Widgets</span>
                  <button className="widget-chooser-reset" onClick={resetWidgets}>Reset defaults</button>
                </div>
                <div className="widget-chooser-list">
                  {WIDGET_REGISTRY.map(w => (
                    <label key={w.id} className={`widget-chooser-item ${visibleWidgets.has(w.id) ? 'active' : ''}`}>
                      <input
                        type="checkbox"
                        checked={visibleWidgets.has(w.id)}
                        onChange={() => toggleWidget(w.id)}
                      />
                      <span className="widget-chooser-icon">{w.icon}</span>
                      <span className="widget-chooser-info">
                        <span className="widget-chooser-label">{w.label}</span>
                        <span className="widget-chooser-desc">{w.description}</span>
                      </span>
                    </label>
                  ))}
                </div>
                <div className="widget-chooser-footer">
                  {visibleWidgets.size} of {WIDGET_REGISTRY.length} widgets visible
                </div>
              </div>
            )}
          </div>
          <button
            className="refresh-button"
            onClick={handleRefresh}
            disabled={loading}
            title="Refresh dashboard"
          >
            {loading ? '⟳ Refreshing...' : '↻ Refresh'}
          </button>
          {lastRefresh && (
            <span className="last-refresh">
              Last updated: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Data freshness banner */}
      {lastRVToolsRun && (
        <div className="data-freshness-banner">
          <span className="freshness-icon">📡</span>
          <span className="freshness-label">Data collected:</span>
          <span className="freshness-time">{new Date(lastRVToolsRun.last_run).toLocaleString()}</span>
          {lastRVToolsRun.duration_seconds != null && (
            <span className="freshness-detail">({lastRVToolsRun.duration_seconds}s run)</span>
          )}
          {(() => {
            const ageMs = Date.now() - new Date(lastRVToolsRun.last_run).getTime();
            const ageMins = Math.round(ageMs / 60000);
            const cls = ageMins > 120 ? 'freshness-age stale' : ageMins > 60 ? 'freshness-age warning' : 'freshness-age fresh';
            const label = ageMins < 1 ? 'just now' : ageMins < 60 ? `${ageMins}m ago` : `${Math.round(ageMins / 60)}h ago`;
            return <span className={cls}>{label}</span>;
          })()}
        </div>
      )}

      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
          <button onClick={handleRefresh} className="retry-button">
            Retry
          </button>
        </div>
      )}

      <div className="dashboard-grid">
        {/* Row 1: Health Summary */}
        {visibleWidgets.has('health') && data.health && <HealthSummaryCard data={data.health} />}

        {/* Row 1: SLA Compliance */}
        {visibleWidgets.has('sla') && data.sla && (
          <SnapshotSLAWidget data={data.sla} onNavigate={onNavigate} />
        )}

        {/* Coverage Risks - Full Width */}
        {visibleWidgets.has('coverage') && data.coverage && (
          <div className="dashboard-section-full">
            <CoverageRiskCard data={data.coverage} />
          </div>
        )}

        {/* Top Hosts */}
        {visibleWidgets.has('hosts') && data.hosts && <HostUtilizationCard data={data.hosts} />}

        {/* Recent Activity */}
        {visibleWidgets.has('activity') && data.activity && <RecentActivityWidget data={data.activity} />}

        {/* VM Hotspots - Full Width */}
        {visibleWidgets.has('vmHotspots') && data.vmHotspotsCpu && data.vmHotspotsMemory && data.vmHotspotsStorage && (
          <div className="dashboard-section-full">
            <VMHotspotsCard
              cpuData={data.vmHotspotsCpu}
              memoryData={data.vmHotspotsMemory}
              storageData={data.vmHotspotsStorage}
            />
          </div>
        )}

        {/* Tenant Risk Scores - Full Width */}
        {visibleWidgets.has('tenantRisk') && data.tenantRisk && (
          <div className="dashboard-section-full">
            <TenantRiskScoreCard data={data.tenantRisk} />
          </div>
        )}

        {/* Tenant Risk Heatmap - Full Width */}
        {visibleWidgets.has('tenantRiskHeatmap') && data.tenantRiskHeatmap && (
          <div className="dashboard-section-full">
            <TenantRiskHeatmapCard data={data.tenantRiskHeatmap} />
          </div>
        )}

        {/* Capacity Pressure */}
        {visibleWidgets.has('capacity') && data.capacity && <CapacityPressureCard data={data.capacity} />}

        {/* Change & Compliance */}
        {visibleWidgets.has('changeCompliance') && data.changeCompliance && <ChangeComplianceCard data={data.changeCompliance} />}

        {/* Compliance Drift Signals */}
        {visibleWidgets.has('complianceDrift') && data.complianceDrift && <ComplianceDriftCard data={data.complianceDrift} />}

        {/* Trendlines - Full Width */}
        {visibleWidgets.has('trendlines') && data.trendlines && (
          <div className="dashboard-section-full">
            <TrendlinesCard data={data.trendlines} />
          </div>
        )}

        {/* Capacity Trends - Full Width */}
        {visibleWidgets.has('capacityTrends') && data.capacityTrends && (
          <div className="dashboard-section-full">
            <CapacityTrendsCard data={data.capacityTrends} />
          </div>
        )}
      </div>

      <div className="dashboard-footer">
        <p>
          Click on any metric to drill down · Auto-refreshes every 60 seconds · Use ⚙ Customize to show/hide widgets
        </p>
      </div>
    </div>
  );
};
