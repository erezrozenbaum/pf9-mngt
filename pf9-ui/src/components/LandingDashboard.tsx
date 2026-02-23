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
  osDistribution: any;
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
  | 'capacityTrends'
  | 'osDistribution';

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
  { id: 'osDistribution', label: 'OS Distribution', icon: '💻', description: 'VM count by operating system', defaultVisible: true },
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
    osDistribution: null,
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

      // Helper: fetch + parse individually; returns null on any failure
      const safeFetch = async (url: string) => {
        try {
          const res = await fetch(url, { headers });
          if (res.status === 401) {
            if (token) {
              localStorage.removeItem('auth_token');
              localStorage.removeItem('auth_user');
              localStorage.removeItem('token_expires_at');
            }
            throw new Error('AUTH_REQUIRED');
          }
          return res.ok ? await res.json() : null;
        } catch (err: unknown) {
          if (err instanceof Error && err.message === 'AUTH_REQUIRED') throw err;
          console.warn(`Dashboard fetch failed: ${url}`, err);
          return null;
        }
      };

      // Batch 1: critical widgets (health + core)
      const [health, sla, hosts, activity, coverage, capacity] = await Promise.all([
        safeFetch(`${API_BASE}/dashboard/health-summary`),
        safeFetch(`${API_BASE}/dashboard/snapshot-sla-compliance`),
        safeFetch(`${API_BASE}/dashboard/top-hosts-utilization`),
        safeFetch(`${API_BASE}/dashboard/recent-changes`),
        safeFetch(`${API_BASE}/dashboard/coverage-risks`),
        safeFetch(`${API_BASE}/dashboard/capacity-pressure`),
      ]);

      // Batch 2: VM hotspots + compliance
      const [vmHotspotsCpu, vmHotspotsMemory, vmHotspotsStorage, changeCompliance, tenantRisk] = await Promise.all([
        safeFetch(`${API_BASE}/dashboard/vm-hotspots?sort=cpu`),
        safeFetch(`${API_BASE}/dashboard/vm-hotspots?sort=memory`),
        safeFetch(`${API_BASE}/dashboard/vm-hotspots?sort=storage`),
        safeFetch(`${API_BASE}/dashboard/change-compliance`),
        safeFetch(`${API_BASE}/dashboard/tenant-risk-scores`),
      ]);

      // Batch 3: trends + analytics
      const [trendlines, tenantRiskHeatmap, capacityTrends, complianceDrift, rvtoolsLastRun, osDistribution] = await Promise.all([
        safeFetch(`${API_BASE}/dashboard/trendlines`),
        safeFetch(`${API_BASE}/dashboard/tenant-risk-heatmap`),
        safeFetch(`${API_BASE}/dashboard/capacity-trends`),
        safeFetch(`${API_BASE}/dashboard/compliance-drift`),
        safeFetch(`${API_BASE}/dashboard/rvtools-last-run`),
        safeFetch(`${API_BASE}/os-distribution`),
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
        osDistribution,
      });
      setLastRefresh(new Date());
      setLastRVToolsRun(rvtoolsLastRun?.last_run ? rvtoolsLastRun : null);
    } catch (err) {
      if (err instanceof Error && err.message === 'AUTH_REQUIRED') {
        setError('Authentication required. Please login.');
      } else {
        setError(
          err instanceof Error ? err.message : 'Failed to load dashboard data'
        );
      }
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
        {visibleWidgets.has('hosts') && data.hosts && <HostUtilizationCard data={data.hosts} isDark={theme === 'dark'} />}

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
            <TenantRiskHeatmapCard data={data.tenantRiskHeatmap} isDark={theme === 'dark'} />
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

        {/* OS Distribution Widget */}
        {visibleWidgets.has('osDistribution') && data.osDistribution && (
          <div className="dashboard-card">
            <div className="card-header">
              <h3>💻 OS Distribution</h3>
            </div>
            <div className="card-body" style={{padding: '16px'}}>
              {(() => {
                const items = data.osDistribution?.items || [];
                if (items.length === 0) return <p style={{color:'#888'}}>No OS data available yet.</p>;
                const total = items.reduce((s: number, d: any) => s + (d.vm_count || 0), 0);
                const colors = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316'];
                return (
                  <div>
                    {items.map((d: any, i: number) => {
                      const pct = total > 0 ? Math.round((d.vm_count / total) * 100) : 0;
                      return (
                        <div key={d.os_distro} style={{display:'flex', alignItems:'center', gap:8, marginBottom:8}}>
                          <span style={{minWidth:80, fontWeight:500, fontSize:'0.9em', textTransform:'capitalize'}}>{d.os_distro || 'unknown'}</span>
                          <div style={{flex:1, height:18, background:'rgba(128,128,128,0.1)', borderRadius:4, overflow:'hidden'}}>
                            <div style={{width:`${pct}%`, height:'100%', background:colors[i % colors.length], borderRadius:4, transition:'width 0.3s'}} />
                          </div>
                          <span style={{minWidth:60, textAlign:'right', fontSize:'0.85em', fontWeight:600}}>{d.vm_count} ({pct}%)</span>
                        </div>
                      );
                    })}
                    <div style={{textAlign:'right', marginTop:8, fontSize:'0.8em', color:'#888'}}>Total: {total} VMs</div>
                  </div>
                );
              })()}
            </div>
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
