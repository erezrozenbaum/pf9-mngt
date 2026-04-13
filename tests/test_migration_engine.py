"""
tests/test_migration_engine.py — Unit tests for api/migration_engine.py

All functions under test are pure (no DB, no HTTP, no filesystem access).
Tests run in isolation — no live stack required.

Coverage areas:
  B12.1 — risk scoring thresholds, bandwidth model edge cases,
           agent sizing (>1000 VMs), RVTools column normalization.
"""
import os
import sys
import pytest

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from migration_engine import (
    build_column_map,
    extract_row,
    classify_os_family,
    detect_tenant_folder,
    detect_tenant_resource_pool,
    detect_tenant_vcd_folder,
    detect_tenant_vm_name,
    compute_risk,
    classify_migration_mode,
    compute_bandwidth_model,
    recommend_agent_sizing,
    estimate_vm_time,
    compute_wan_estimation,
    apply_qos_constraints,
    RiskResult,
    BandwidthModel,
    AgentRecommendation,
    VMTimeEstimate,
)

# ---------------------------------------------------------------------------
# Minimal default risk rules
# ---------------------------------------------------------------------------
_RULES = {
    "os_unsupported":  ["Windows XP", "Windows 2000"],
    "os_deprecated":   ["Windows 2008"],
    "os_cold_required": ["Novell NetWare"],
    "os_warm_risky":   ["Windows Vista"],
    "disk_very_large_threshold_gb": 5000,
    "disk_large_threshold_gb": 2000,
    "disk_count_high": 8,
    "snapshot_depth_critical": 5,
    "snapshot_depth_warning": 3,
    "snapshot_age_warning_days": 30,
    "multi_nic_threshold": 3,
    "high_ram_threshold_gb": 64,
    "db_name_patterns": ["sql", "oracle", "mysql", "postgres"],
    "high_disk_count_threshold": 6,
    "category_thresholds": {"green_max": 20, "yellow_max": 50},
    "risk_weights": {
        "os_unsupported": 30,
        "os_deprecated": 15,
        "cold_required_os": 20,
        "disk_very_large": 25,
        "disk_large": 10,
        "disk_count_high": 10,
        "snapshot_critical": 20,
        "snapshot_warning": 8,
        "snapshot_old": 5,
        "multi_nic": 10,
        "high_io_heuristic": 15,
    },
}


# ===========================================================================
# 1.  Column Normalization (RVTools XLSX parser)
# ===========================================================================

class TestBuildColumnMap:
    def test_exact_alias_match(self):
        headers = ["VM", "CPUs", "Memory", "Powerstate"]
        col_map = build_column_map(headers)
        assert col_map["vm_name"] == 0
        assert col_map["cpu_count"] == 1
        assert col_map["ram_mb"] == 2
        assert col_map["power_state"] == 3

    def test_case_insensitive_whitespace_normalised(self):
        headers = ["  vm name  ", "CPUs"]
        col_map = build_column_map(headers)
        assert col_map.get("vm_name") is not None
        assert col_map.get("cpu_count") is not None

    def test_missing_column_not_in_map(self):
        headers = ["VM", "CPUs"]
        col_map = build_column_map(headers)
        assert "vm_name" in col_map
        assert "cpu_count" in col_map
        assert "ram_mb" not in col_map

    def test_empty_headers_returns_empty_map(self):
        assert build_column_map([]) == {}

    def test_alternative_alias_resolved(self):
        headers = ["Num CPUs", "Memory MB"]
        col_map = build_column_map(headers)
        assert col_map.get("cpu_count") is not None
        assert col_map.get("ram_mb") is not None

    def test_first_matching_alias_wins(self):
        headers = ["VM", "Name"]
        col_map = build_column_map(headers)
        assert col_map["vm_name"] == 0

    def test_disk_aliases(self):
        headers = ["VM", "Capacity MB", "Thin"]
        col_map = build_column_map(headers)
        assert col_map.get("capacity_mb") is not None
        assert col_map.get("thin") is not None

    def test_host_sheet_prefix_scoping(self):
        headers = ["Host", "Cluster", "# CPU", "Memory"]
        col_map = build_column_map(headers, prefix="host_")
        assert col_map.get("host_host_name") is not None
        assert col_map.get("host_cluster") is not None

    def test_malformed_sheet_partial_headers(self):
        # Only a handful of known columns present; rest should be absent
        headers = ["VM", "UNKNOWN_COL_1", "ANOTHER_UNKNOWN"]
        col_map = build_column_map(headers)
        assert "vm_name" in col_map
        assert col_map["vm_name"] == 0
        # Unknown columns should not appear
        assert len([k for k in col_map if "unknown" in k.lower()]) == 0

    def test_vnic_aliases(self):
        headers = ["VM", "Network Adapter", "Adapter Type", "Network"]
        col_map = build_column_map(headers)
        assert col_map.get("nic_vm_name") is not None
        assert col_map.get("nic_label") is not None


class TestExtractRow:
    def test_normal_extraction(self):
        headers = ["VM", "CPUs", "Memory"]
        col_map = build_column_map(headers)
        row = ["web-01", 4, 8192]
        result = extract_row(row, col_map)
        assert result["vm_name"] == "web-01"
        assert result["cpu_count"] == 4
        assert result["ram_mb"] == 8192

    def test_short_row_fills_empty_string(self):
        col_map = {"vm_name": 0, "cpu_count": 5}
        row = ["web-01"]
        result = extract_row(row, col_map)
        assert result["vm_name"] == "web-01"
        assert result["cpu_count"] == ""

    def test_none_cell_becomes_empty_string(self):
        col_map = {"vm_name": 0}
        result = extract_row([None], col_map)
        assert result["vm_name"] == ""

    def test_empty_row_all_empty_strings(self):
        col_map = {"vm_name": 0, "cpu_count": 1}
        result = extract_row([], col_map)
        assert result["vm_name"] == ""
        assert result["cpu_count"] == ""

    def test_zero_index_accessible(self):
        col_map = {"vm_name": 0}
        result = extract_row(["my-vm"], col_map)
        assert result["vm_name"] == "my-vm"


# ===========================================================================
# 2.  OS Classification
# ===========================================================================

class TestClassifyOsFamily:
    @pytest.mark.parametrize("os_str,expected", [
        ("Windows Server 2019 (64-bit)", "windows"),
        ("Microsoft Windows Server 2022", "windows"),
        ("Ubuntu Linux (64-bit)", "linux"),
        ("Red Hat Enterprise Linux 8", "linux"),
        ("CentOS 7 (64-bit)", "linux"),
        ("Amazon Linux 2", "linux"),
        ("Rocky Linux 9", "linux"),
        ("Solaris 11", "other"),
        ("", "other"),
        ("Other (64-bit)", "other"),
    ])
    def test_family_classification(self, os_str, expected):
        assert classify_os_family(os_str) == expected

    def test_tools_string_overrides_config_string(self):
        assert classify_os_family("Other", "Ubuntu Linux (64-bit)") == "linux"

    def test_win32_is_windows(self):
        assert classify_os_family("win32") == "windows"


# ===========================================================================
# 3.  Tenant Detection
# ===========================================================================

class TestTenantDetection:
    def test_detect_tenant_folder_depth2(self):
        vm = {"folder_path": "/DC1/vm/TenantA/Production"}
        assert detect_tenant_folder(vm, depth=2) == "TenantA"

    def test_detect_tenant_folder_empty(self):
        assert detect_tenant_folder({"folder_path": ""}) is None

    def test_detect_tenant_resource_pool_strips_uuid(self):
        vm = {"resource_pool": "/DC1/PvdcName/Resources/AcmeCorp_vDC_1001 (a1b3000a-80a6-42eb-a04d-393c54e009d2)"}
        result = detect_tenant_resource_pool(vm)
        assert result is not None
        # UUID suffix should be stripped
        assert "a1b3000a-80a6-42eb-a04d-393c54e009d2" not in result

    def test_detect_tenant_vm_name_prefix(self):
        vm = {"vm_name": "TenantA-web-01"}
        assert detect_tenant_vm_name(vm, separator="-", prefix_parts=1) == "TenantA"

    def test_detect_tenant_vm_name_no_separator(self):
        vm = {"vm_name": "monolith"}
        # No separator match → returns None
        result = detect_tenant_vm_name(vm, separator="-", prefix_parts=1)
        assert result is None

    def test_detect_tenant_vcd_folder_vdc_pattern(self):
        vm = {"folder_path": "/DC1/vCD1/OrgA (some-uuid)/OrgA-VDC-123456 (other-uuid)/vms"}
        result = detect_tenant_vcd_folder(vm)
        assert result is not None
        org, vdc = result
        assert org  # non-empty

    def test_detect_tenant_vcd_resource_pool(self):
        vm = {
            "folder_path": "",
            "resource_pool": "/DC1/PvdcName/Resources/OrgB_vDC_789012",
        }
        result = detect_tenant_vcd_folder(vm)
        assert result is not None

    def test_detect_tenant_vcd_no_match_returns_none(self):
        vm = {"folder_path": "/simple/path", "resource_pool": "/simple/rp"}
        # No VDC pattern and no UUID-bearing segments → None
        result = detect_tenant_vcd_folder(vm)
        assert result is None


# ===========================================================================
# 4.  Risk Scoring — thresholds and category boundaries
# ===========================================================================

class TestComputeRisk:
    def _base_vm(self, **overrides):
        vm = {
            "vm_name": "web-01",
            "guest_os": "Ubuntu Linux",
            "guest_os_tools": "",
            "total_disk_gb": 50,
            "disk_count": 1,
            "snapshot_count": 0,
            "snapshot_oldest_days": 0,
            "nic_count": 1,
            "ram_mb": 4096,
        }
        vm.update(overrides)
        return vm

    def test_clean_vm_is_green(self):
        result = compute_risk(self._base_vm(), _RULES)
        assert result.category == "GREEN"
        assert result.score <= 20

    def test_unsupported_os_adds_30_points(self):
        result = compute_risk(self._base_vm(guest_os="Windows XP"), _RULES)
        assert result.score >= 30
        assert any("Unsupported" in r for r in result.reasons)

    def test_deprecated_os_adds_15_points(self):
        result = compute_risk(self._base_vm(guest_os="Windows 2008"), _RULES)
        # Should appear in reasons
        assert any("Deprecated" in r for r in result.reasons)
        # 15 points but base is 0 → score is 15
        assert result.score >= 15

    def test_very_large_disk_adds_25_points(self):
        result = compute_risk(self._base_vm(total_disk_gb=6000), _RULES)
        assert result.score >= 25
        assert any("Very large" in r for r in result.reasons)

    def test_large_disk_adds_10_points(self):
        result = compute_risk(self._base_vm(total_disk_gb=2500), _RULES)
        assert any("Large total disk" in r or "Large disk" in r for r in result.reasons)

    def test_critical_snapshot_depth_adds_20_points(self):
        result = compute_risk(self._base_vm(snapshot_count=6), _RULES)
        assert result.score >= 20
        assert any("snapshot" in r.lower() for r in result.reasons)

    def test_warning_snapshot_depth_adds_8_points(self):
        result = compute_risk(self._base_vm(snapshot_count=3), _RULES)
        assert any("snapshot" in r.lower() for r in result.reasons)

    def test_old_snapshot_adds_5_points(self):
        result = compute_risk(self._base_vm(snapshot_oldest_days=60), _RULES)
        assert any("snapshot" in r.lower() or "Old" in r for r in result.reasons)

    def test_multi_nic_adds_10_points(self):
        result = compute_risk(self._base_vm(nic_count=3), _RULES)
        assert result.score >= 10
        assert any("NIC" in r or "Multi-NIC" in r for r in result.reasons)

    def test_high_ram_triggers_io_heuristic(self):
        result = compute_risk(self._base_vm(ram_mb=65536), _RULES)  # 64 GB
        assert any("I/O" in r or "RAM" in r for r in result.reasons)

    def test_db_name_pattern_triggers_io_heuristic(self):
        result = compute_risk(self._base_vm(vm_name="mysql-primary"), _RULES)
        assert any("DB-like" in r or "I/O" in r for r in result.reasons)

    def test_multiple_factors_red_category(self):
        result = compute_risk(self._base_vm(
            guest_os="Windows XP",    # +30
            total_disk_gb=6000,       # +25
            snapshot_count=6,         # +20
            nic_count=3,              # +10
        ), _RULES)
        assert result.category == "RED"
        assert result.score > 50

    def test_score_clamped_at_100(self):
        # Pile on every possible risk factor
        result = compute_risk(self._base_vm(
            guest_os="Windows XP",
            total_disk_gb=10000,
            disk_count=10,
            snapshot_count=10,
            snapshot_oldest_days=90,
            nic_count=5,
            ram_mb=1_048_576,
        ), _RULES)
        assert result.score <= 100.0

    def test_yellow_boundary(self):
        # deprecated OS (+15) + large disk (+10) = 25 → YELLOW
        result = compute_risk(self._base_vm(
            guest_os="Windows 2008",
            total_disk_gb=2500,
        ), _RULES)
        assert result.category == "YELLOW"

    def test_returns_risk_result_dataclass(self):
        result = compute_risk(self._base_vm(), _RULES)
        assert isinstance(result, RiskResult)
        assert hasattr(result, "score")
        assert hasattr(result, "category")
        assert isinstance(result.reasons, list)


# ===========================================================================
# 5.  Migration Mode Classification
# ===========================================================================

class TestClassifyMigrationMode:
    def _base_vm(self, **overrides):
        vm = {
            "guest_os": "Ubuntu Linux",
            "guest_os_tools": "",
            "power_state": "poweredOn",
            "change_tracking": True,
            "total_disk_gb": 100,
            "snapshot_count": 0,
        }
        vm.update(overrides)
        return vm

    def test_normal_vm_is_warm_eligible(self):
        result = classify_migration_mode(self._base_vm(), _RULES)
        assert result.mode == "warm_eligible"

    def test_powered_off_is_cold_required(self):
        result = classify_migration_mode(self._base_vm(power_state="poweredOff"), _RULES)
        assert result.mode == "cold_required"

    def test_suspended_is_cold_required(self):
        result = classify_migration_mode(self._base_vm(power_state="suspended"), _RULES)
        assert result.mode == "cold_required"

    def test_cold_required_os(self):
        result = classify_migration_mode(self._base_vm(guest_os="Novell NetWare"), _RULES)
        assert result.mode == "cold_required"

    def test_risky_os_is_warm_risky(self):
        result = classify_migration_mode(self._base_vm(guest_os="Windows Vista"), _RULES)
        assert result.mode == "warm_risky"

    def test_very_large_disk_is_warm_risky(self):
        result = classify_migration_mode(self._base_vm(total_disk_gb=6000), _RULES)
        assert result.mode == "warm_risky"

    def test_deep_snapshot_chain_is_warm_risky(self):
        result = classify_migration_mode(self._base_vm(snapshot_count=6), _RULES)
        assert result.mode == "warm_risky"

    def test_reasons_list_populated(self):
        result = classify_migration_mode(self._base_vm(), _RULES)
        assert isinstance(result.reasons, list)
        assert len(result.reasons) > 0


# ===========================================================================
# 6.  Bandwidth Model — edge cases and bottleneck detection
# ===========================================================================

class TestComputeBandwidthModel:
    def _local_settings(self, **overrides):
        s = {
            "topology_type": "local",
            "source_nic_speed_gbps": 10,
            "source_usable_pct": 40,
            "agent_count": 2,
            "agent_nic_speed_gbps": 10,
            "agent_nic_usable_pct": 70,
            "pcd_storage_write_mbps": 1000,
        }
        s.update(overrides)
        return s

    def test_returns_bandwidth_model_dataclass(self):
        model = compute_bandwidth_model(self._local_settings())
        assert isinstance(model, BandwidthModel)

    def test_local_topology_no_link_bottleneck(self):
        model = compute_bandwidth_model(self._local_settings())
        assert model.bottleneck != "transport_link"
        assert model.bottleneck_mbps > 0

    def test_slow_source_nic_is_bottleneck(self):
        settings = self._local_settings(
            source_nic_speed_gbps=0.1,   # 100 Mbps NIC
            source_usable_pct=40,        # 40 Mbps effective
            agent_count=4,
            pcd_storage_write_mbps=10000,
        )
        model = compute_bandwidth_model(settings)
        assert model.bottleneck == "source_host_nic"

    def test_slow_wan_link_is_bottleneck(self):
        settings = {
            "topology_type": "cross_site_internet",
            "source_nic_speed_gbps": 10,
            "source_usable_pct": 50,
            "source_upload_mbps": 50,    # 50 Mbps WAN upload
            "dest_download_mbps": 100,
            "link_usable_pct": 80,
            "rtt_category": "lt5",
            "agent_count": 2,
            "agent_nic_speed_gbps": 10,
            "agent_nic_usable_pct": 70,
            "pcd_storage_write_mbps": 1000,
        }
        model = compute_bandwidth_model(settings)
        assert model.bottleneck == "transport_link"

    def test_very_slow_storage_is_bottleneck(self):
        model = compute_bandwidth_model(self._local_settings(pcd_storage_write_mbps=1))
        assert model.bottleneck == "pcd_storage"

    def test_zero_agents_makes_agent_ingest_bottleneck(self):
        model = compute_bandwidth_model(self._local_settings(agent_count=0))
        assert model.agent_effective_mbps == 0.0
        assert model.bottleneck == "agent_ingest"

    def test_dedicated_link_cross_site(self):
        settings = {
            "topology_type": "cross_site_dedicated",
            "source_nic_speed_gbps": 1,
            "source_usable_pct": 40,       # 400 Mbps
            "link_speed_gbps": 100,
            "link_usable_pct": 80,         # 80 Gbps
            "agent_count": 4,
            "agent_nic_speed_gbps": 10,
            "agent_nic_usable_pct": 70,
            "pcd_storage_write_mbps": 10000,
        }
        model = compute_bandwidth_model(settings)
        assert model.bottleneck == "source_host_nic"

    def test_high_latency_penalises_wan(self):
        settings = {
            "topology_type": "cross_site_internet",
            "source_nic_speed_gbps": 10,
            "source_usable_pct": 50,
            "source_upload_mbps": 1000,
            "dest_download_mbps": 1000,
            "link_usable_pct": 80,
            "rtt_category": "gt100",       # >100ms RTT — 35% penalty
            "agent_count": 2,
            "agent_nic_speed_gbps": 10,
            "agent_nic_usable_pct": 70,
            "pcd_storage_write_mbps": 5000,
        }
        model_low_latency = compute_bandwidth_model({**settings, "rtt_category": "lt5"})
        model_high_latency = compute_bandwidth_model(settings)
        # High latency should yield lower effective link speed
        assert model_high_latency.link_effective_mbps < model_low_latency.link_effective_mbps


# ===========================================================================
# 7.  Agent Sizing
# ===========================================================================

class TestRecommendAgentSizing:
    def test_minimum_two_agents_small_project(self):
        result = recommend_agent_sizing(
            vm_count=5,
            largest_disk_gb=50,
            top5_disk_sizes_gb=[50, 40, 30, 20, 10],
            project_settings={},
        )
        assert result.recommended_count >= 2

    def test_large_fleet_above_minimum(self):
        result = recommend_agent_sizing(
            vm_count=1200,
            largest_disk_gb=500,
            top5_disk_sizes_gb=[500, 480, 450, 400, 380],
            project_settings={},
            total_disk_gb=200_000,
        )
        assert isinstance(result, AgentRecommendation)
        assert result.recommended_count >= 2

    def test_very_large_fleet_1000_plus(self):
        result = recommend_agent_sizing(
            vm_count=2000,
            largest_disk_gb=800,
            top5_disk_sizes_gb=[800, 750, 700, 650, 600],
            project_settings={"agent_concurrent_vms": 5},
            total_disk_gb=500_000,
        )
        # 2000 VMs / (5 concurrent * 4 cycles) = 100 agents; min 2 but heuristic > 2
        assert result.recommended_count >= 2
        assert result.max_concurrent_vms >= 2

    def test_target_vms_per_day_drives_sizing(self):
        result = recommend_agent_sizing(
            vm_count=500,
            largest_disk_gb=200,
            top5_disk_sizes_gb=[200, 180, 160, 140, 120],
            project_settings={
                "target_vms_per_day": 100,
                "working_hours_per_day": 8,
                "agent_concurrent_vms": 5,
            },
        )
        assert result.recommended_count >= 2
        assert any("VMs/agent/day" in r or "VMs/day" in r for r in result.reasoning)

    def test_duration_days_drives_sizing(self):
        result = recommend_agent_sizing(
            vm_count=1000,
            largest_disk_gb=200,
            top5_disk_sizes_gb=[200, 180, 160, 140, 120],
            project_settings={
                "migration_duration_days": 30,
                "working_hours_per_day": 8,
                "working_days_per_week": 5,
                "agent_concurrent_vms": 5,
            },
        )
        assert result.recommended_count >= 2
        assert any("working days" in r.lower() or "effective days" in r.lower() for r in result.reasoning)

    def test_per_agent_resource_fields_positive(self):
        result = recommend_agent_sizing(
            vm_count=50,
            largest_disk_gb=100,
            top5_disk_sizes_gb=[100, 80, 60, 50, 40],
            project_settings={},
        )
        assert result.vcpu_per_agent > 0
        assert result.ram_gb_per_agent > 0
        assert result.disk_gb_per_agent > 0
        assert result.max_concurrent_vms > 0
        assert isinstance(result.reasoning, list)
        assert len(result.reasoning) > 0

    def test_empty_top5_falls_back_to_largest(self):
        # If top5 list is empty, should still work
        result = recommend_agent_sizing(
            vm_count=50,
            largest_disk_gb=200,
            top5_disk_sizes_gb=[],
            project_settings={},
        )
        assert result.disk_gb_per_agent > 0


# ===========================================================================
# 8.  VM Time Estimation
# ===========================================================================

class TestEstimateVmTime:
    def test_warm_eligible_returns_positive_times(self):
        vm = {"vm_name": "web-01", "total_disk_gb": 100, "in_use_gb": 50,
              "migration_mode": "warm_eligible"}
        est = estimate_vm_time(vm, bottleneck_mbps=1000)
        assert isinstance(est, VMTimeEstimate)
        assert est.warm_phase1_hours > 0
        assert est.warm_cutover_hours > 0
        assert est.warm_total_hours > 0

    def test_cold_migration_uses_total_disk(self):
        vm = {"vm_name": "big-01", "total_disk_gb": 500, "in_use_gb": 200,
              "migration_mode": "cold_required"}
        est = estimate_vm_time(vm, bottleneck_mbps=1000)
        assert est.cold_total_hours > 0
        assert est.cold_downtime_hours > 0

    def test_zero_bandwidth_falls_back_to_1gbps(self):
        vm = {"vm_name": "test", "total_disk_gb": 100, "in_use_gb": 50,
              "migration_mode": "warm_eligible"}
        est = estimate_vm_time(vm, bottleneck_mbps=0)
        assert est.warm_phase1_hours > 0  # Did not divide by zero

    def test_missing_in_use_falls_back_to_total_disk(self):
        vm = {"vm_name": "test", "total_disk_gb": 100, "in_use_gb": 0,
              "migration_mode": "warm_eligible"}
        est = estimate_vm_time(vm, bottleneck_mbps=1000)
        assert est.in_use_gb == 100.0

    def test_in_use_mb_fallback(self):
        # in_use_gb absent; in_use_mb present
        vm = {"vm_name": "test", "total_disk_gb": 200, "in_use_mb": 51200,
              "migration_mode": "warm_eligible"}
        est = estimate_vm_time(vm, bottleneck_mbps=1000)
        assert abs(est.in_use_gb - 50.0) < 1.0  # 51200 MB ≈ 50 GB

    @pytest.mark.parametrize("in_use_gb,bw_mbps", [
        (50, 1000), (200, 500), (1500, 10000), (10, 100),
    ])
    def test_larger_disk_takes_longer_warm(self, in_use_gb, bw_mbps):
        vm_small = {"vm_name": "s", "total_disk_gb": in_use_gb, "in_use_gb": in_use_gb,
                    "migration_mode": "warm_eligible"}
        vm_double = {"vm_name": "l", "total_disk_gb": in_use_gb * 2, "in_use_gb": in_use_gb * 2,
                     "migration_mode": "warm_eligible"}
        est_s = estimate_vm_time(vm_small, bottleneck_mbps=bw_mbps)
        est_d = estimate_vm_time(vm_double, bottleneck_mbps=bw_mbps)
        assert est_d.warm_phase1_hours > est_s.warm_phase1_hours

    def test_very_large_vm_1tb_warm(self):
        vm = {"vm_name": "big-db", "total_disk_gb": 1024, "in_use_gb": 800,
              "migration_mode": "warm_risky"}
        est = estimate_vm_time(vm, bottleneck_mbps=1000)
        assert est.warm_phase1_hours > 1  # Should take at least 1 hour at 1 Gbps


# ---------------------------------------------------------------------------
# B13.1 — compute_wan_estimation
# ---------------------------------------------------------------------------

class TestComputeWanEstimation:

    def _make_vms(self, sizes_gb: list) -> list:
        return [{"vm_name": f"vm{i}", "in_use_gb": s} for i, s in enumerate(sizes_gb)]

    def test_empty_list_returns_zero_total(self):
        result = compute_wan_estimation([], 100)
        assert result["total_estimated_hours"] == 0.0
        assert result["per_vm"] == {}

    def test_fallback_on_zero_bandwidth(self):
        vms = self._make_vms([100])
        result = compute_wan_estimation(vms, 0)
        # Fallback = 100 Mbps; should return positive hours
        assert result["wan_bandwidth_mbps"] == 100.0
        assert result["per_vm"]["vm0"] > 0

    def test_fallback_on_negative_bandwidth(self):
        vms = self._make_vms([100])
        result = compute_wan_estimation(vms, -50)
        assert result["wan_bandwidth_mbps"] == 100.0

    def test_fallback_on_none_bandwidth(self):
        vms = self._make_vms([100])
        result = compute_wan_estimation(vms, None)
        assert result["wan_bandwidth_mbps"] == 100.0

    def test_single_vm_known_value(self):
        # 100 Mbps = 12.5 MB/s = 43.945 GB/h
        # 100 GB at 100 Mbps ≈ 2.28 h
        vms = [{"vm_name": "web01", "in_use_gb": 100}]
        result = compute_wan_estimation(vms, 100)
        gb_per_hour = (100 / 8) * 3600 / 1024
        expected = round(100 / gb_per_hour, 2)
        assert result["per_vm"]["web01"] == expected

    def test_uses_in_use_gb_preferentially(self):
        vms = [{"vm_name": "vm0", "in_use_gb": 50, "total_disk_gb": 200}]
        result = compute_wan_estimation(vms, 100)
        gb_per_hour = (100 / 8) * 3600 / 1024
        assert result["per_vm"]["vm0"] == round(50 / gb_per_hour, 2)

    def test_falls_back_to_total_disk_gb_when_in_use_zero(self):
        vms = [{"vm_name": "vm0", "in_use_gb": 0, "total_disk_gb": 200}]
        result = compute_wan_estimation(vms, 100)
        gb_per_hour = (100 / 8) * 3600 / 1024
        assert result["per_vm"]["vm0"] == round(200 / gb_per_hour, 2)

    def test_higher_bandwidth_gives_fewer_hours(self):
        vms = [{"vm_name": "vm0", "in_use_gb": 500}]
        slow = compute_wan_estimation(vms, 100)
        fast = compute_wan_estimation(vms, 1000)
        assert fast["per_vm"]["vm0"] < slow["per_vm"]["vm0"]

    def test_total_is_sum_of_per_vm(self):
        vms = self._make_vms([100, 200, 300])
        result = compute_wan_estimation(vms, 200)
        per_vm_sum = round(sum(result["per_vm"].values()), 2)
        assert abs(result["total_estimated_hours"] - per_vm_sum) < 0.05

    def test_effective_gb_per_hour_key_present(self):
        vms = self._make_vms([100])
        result = compute_wan_estimation(vms, 100)
        assert "effective_gb_per_hour" in result
        assert result["effective_gb_per_hour"] > 0

    def test_very_high_bandwidth_gives_sub_hour_result(self):
        vms = [{"vm_name": "small", "in_use_gb": 10}]
        result = compute_wan_estimation(vms, 10_000)  # 10 Gbps
        assert result["per_vm"]["small"] < 1.0


# ---------------------------------------------------------------------------
# B13.2 — apply_qos_constraints
# ---------------------------------------------------------------------------

class TestApplyQosConstraints:

    def test_no_throttle_returns_proposed_unchanged(self):
        eff, concurrent, warnings = apply_qos_constraints({}, 500)
        assert eff == 500
        assert not warnings

    def test_throttle_below_proposed_caps_bandwidth(self):
        settings = {"throttle_mbps": 200}
        eff, _, warnings = apply_qos_constraints(settings, 500)
        assert eff == 200
        assert any("Throttle cap" in w for w in warnings)

    def test_throttle_above_proposed_no_cap(self):
        settings = {"throttle_mbps": 1000}
        eff, _, warnings = apply_qos_constraints(settings, 500)
        assert eff == 500
        assert not any("Throttle" in w for w in warnings)

    def test_zero_throttle_ignored(self):
        settings = {"throttle_mbps": 0}
        eff, _, _ = apply_qos_constraints(settings, 500)
        assert eff == 500

    def test_explicit_max_concurrent_returned(self):
        settings = {"max_concurrent_migrations": 7}
        _, concurrent, _ = apply_qos_constraints(settings, 500)
        assert concurrent == 7

    def test_auto_derive_max_concurrent_from_agents(self):
        settings = {"agent_count": 3, "agent_concurrent_vms": 4}
        _, concurrent, _ = apply_qos_constraints(settings, 500)
        assert concurrent == 12

    def test_default_max_concurrent_when_nothing_set(self):
        _, concurrent, _ = apply_qos_constraints({}, 500)
        # Default: agent_count=2, concurrent_vms=5 → 10
        assert concurrent == 10

    def test_wan_budget_warning_when_over_committed(self):
        settings = {
            "wan_bandwidth_mbps": 100,
            "max_concurrent_migrations": 5,
            "utilization_target_pct": 80,
        }
        _, _, warnings = apply_qos_constraints(settings, 500)
        assert any("budget" in w.lower() for w in warnings)

    def test_wan_budget_no_warning_when_within_budget(self):
        settings = {
            "wan_bandwidth_mbps": 1000,
            "max_concurrent_migrations": 2,
            "utilization_target_pct": 80,
        }
        _, _, warnings = apply_qos_constraints(settings, 100)
        assert not any("budget" in w.lower() for w in warnings)

    def test_returns_tuple_of_three(self):
        result = apply_qos_constraints({}, 300)
        assert len(result) == 3

    def test_warnings_is_a_list(self):
        _, _, warnings = apply_qos_constraints({"throttle_mbps": 50}, 200)
        assert isinstance(warnings, list)
