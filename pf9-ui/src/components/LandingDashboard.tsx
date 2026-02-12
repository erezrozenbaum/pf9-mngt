import React, { useEffect, useState } from 'react';
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

const API_BASE = 'http://localhost:8000';

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

export const LandingDashboard: React.FC = () => {
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

      if (
        !healthRes.ok ||
        !slaRes.ok ||
        !hostsRes.ok ||
        !activityRes.ok ||
        !coverageRes.ok ||
        !capacityRes.ok ||
        !vmCpuRes.ok ||
        !vmMemRes.ok ||
        !vmStorageRes.ok ||
        !changeComplianceRes.ok ||
        !tenantRiskRes.ok ||
        !trendlinesRes.ok ||
        !tenantRiskHeatmapRes.ok ||
        !capacityTrendsRes.ok ||
        !complianceDriftRes.ok
      ) {
        throw new Error('Failed to fetch dashboard data');
      }

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
        healthRes.json(),
        slaRes.json(),
        hostsRes.json(),
        activityRes.json(),
        coverageRes.json(),
        capacityRes.json(),
        vmCpuRes.json(),
        vmMemRes.json(),
        vmStorageRes.json(),
        changeComplianceRes.json(),
        tenantRiskRes.json(),
        trendlinesRes.json(),
        tenantRiskHeatmapRes.json(),
        capacityTrendsRes.json(),
        complianceDriftRes.json(),
        rvtoolsRes.json(),
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
          <h1>🏠 Operations Dashboard</h1>
          <p className="subtitle">Your morning coffee view of infrastructure health</p>
        </div>
        <div className="header-actions">
          <button
            className="refresh-button"
            onClick={handleRefresh}
            disabled={loading}
            title="Refresh dashboard"
          >
            {loading ? '⟳ Refreshing...' : '🔄 Refresh'}
          </button>
          {lastRefresh && (
            <span className="last-refresh">
              Last updated: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          {lastRVToolsRun && (
            <span className="last-rvtools-run">
              Data from: {new Date(lastRVToolsRun.last_run).toLocaleString()}
            </span>
          )}
        </div>
      </div>

      {/* Data freshness banner */}
      <div className="data-freshness-banner">
        <span className="freshness-icon">📡</span>
        {lastRVToolsRun ? (
          <>
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
          </>
        ) : (
          <span className="freshness-label" style={{color: '#f5d1b9'}}>No inventory data collected yet</span>
        )}
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
          <button onClick={handleRefresh} className="retry-button">
            Retry
          </button>
        </div>
      )}

      <div className="dashboard-grid">
        {/* Health Summary - Top Left */}
        {data.health && <HealthSummaryCard data={data.health} />}

        {/* SLA Compliance - Full Width Below Health */}
        {data.sla && (
          <div className="dashboard-section-full">
            <SnapshotSLAWidget data={data.sla} />
          </div>
        )}

        {/* Coverage Risks - Full Width */}
        {data.coverage && (
          <div className="dashboard-section-full">
            <CoverageRiskCard data={data.coverage} />
          </div>
        )}

        {/* Top Hosts - Bottom Left */}
        {data.hosts && <HostUtilizationCard data={data.hosts} />}

        {/* Recent Activity - Bottom Right */}
        {data.activity && <RecentActivityWidget data={data.activity} />}

        {/* VM Hotspots - Full Width */}
        {data.vmHotspotsCpu && data.vmHotspotsMemory && data.vmHotspotsStorage && (
          <div className="dashboard-section-full">
            <VMHotspotsCard
              cpuData={data.vmHotspotsCpu}
              memoryData={data.vmHotspotsMemory}
              storageData={data.vmHotspotsStorage}
            />
          </div>
        )}

        {/* Tenant Risk Scores - Full Width */}
        {data.tenantRisk && (
          <div className="dashboard-section-full">
            <TenantRiskScoreCard data={data.tenantRisk} />
          </div>
        )}

        {/* Tenant Risk Heatmap - Full Width */}
        {data.tenantRiskHeatmap && (
          <div className="dashboard-section-full">
            <TenantRiskHeatmapCard data={data.tenantRiskHeatmap} />
          </div>
        )}

        {/* Capacity Pressure */}
        {data.capacity && <CapacityPressureCard data={data.capacity} />}

        {/* Change & Compliance */}
        {data.changeCompliance && <ChangeComplianceCard data={data.changeCompliance} />}

        {/* Compliance Drift Signals */}
        {data.complianceDrift && <ComplianceDriftCard data={data.complianceDrift} />}

        {/* Trendlines - Full Width */}
        {data.trendlines && (
          <div className="dashboard-section-full">
            <TrendlinesCard data={data.trendlines} />
          </div>
        )}

        {/* Capacity Trends - Full Width */}
        {data.capacityTrends && (
          <div className="dashboard-section-full">
            <CapacityTrendsCard data={data.capacityTrends} />
          </div>
        )}
      </div>

      <div className="dashboard-footer">
        <p>
          💡 Tip: Click on any metric to drill down into details. This dashboard auto-refreshes every 60 seconds.
        </p>
      </div>
    </div>
  );
};
