"""
tests/test_find_zombie_assets.py
Unit tests for the zombie asset scanner.
Mocks all boto3 calls — no AWS credentials required.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from find_zombie_assets import (
    find_idle_ec2,
    find_unassociated_eips,
    find_unattached_ebs,
)


def _utcnow():
    return datetime.now(tz=timezone.utc)


# ── find_unattached_ebs ───────────────────────────────────────────────────────
class TestFindUnattachedEbs:
    def _ec2(self, volumes):
        ec2 = MagicMock()
        pager = MagicMock()
        pager.paginate.return_value = [{"Volumes": volumes}]
        ec2.get_paginator.return_value = pager
        return ec2

    def _vol(self, vol_id, size, vol_type="gp3", tags=None):
        return {
            "VolumeId": vol_id,
            "Size": size,
            "VolumeType": vol_type,
            "CreateTime": _utcnow(),
            "Tags": tags or [],
        }

    def test_flags_unattached_volume_as_high_risk(self):
        result = find_unattached_ebs(self._ec2([self._vol("vol-001", 50)]))
        assert len(result) == 1
        assert result[0]["resource_id"] == "vol-001"
        assert result[0]["risk"] == "HIGH"

    def test_calculates_waste_correctly_for_gp3(self):
        result = find_unattached_ebs(self._ec2([self._vol("vol-001", 100, "gp3")]))
        assert result[0]["monthly_waste_usd"] == pytest.approx(8.0)

    def test_calculates_waste_correctly_for_gp2(self):
        result = find_unattached_ebs(self._ec2([self._vol("vol-001", 100, "gp2")]))
        assert result[0]["monthly_waste_usd"] == pytest.approx(10.0)

    def test_uses_name_tag_when_present(self):
        tags = [{"Key": "Name", "Value": "my-volume"}]
        result = find_unattached_ebs(self._ec2([self._vol("vol-001", 20, tags=tags)]))
        assert result[0]["name"] == "my-volume"

    def test_uses_volume_id_as_name_when_tag_absent(self):
        result = find_unattached_ebs(self._ec2([self._vol("vol-001", 20)]))
        assert result[0]["name"] == "vol-001"

    def test_empty_account_returns_empty_list(self):
        assert find_unattached_ebs(self._ec2([])) == []

    def test_three_volumes_all_flagged(self):
        vols = [self._vol(f"vol-00{i}", i * 10) for i in range(1, 4)]
        result = find_unattached_ebs(self._ec2(vols))
        assert len(result) == 3

    def test_total_waste_sums_correctly(self):
        vols = [self._vol("vol-a", 20, "gp3"), self._vol("vol-b", 30, "gp3")]
        result = find_unattached_ebs(self._ec2(vols))
        total = sum(r["monthly_waste_usd"] for r in result)
        assert total == pytest.approx(20 * 0.08 + 30 * 0.08)


# ── find_unassociated_eips ────────────────────────────────────────────────────
class TestFindUnassociatedEips:
    def _ec2(self, addresses):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {"Addresses": addresses}
        return ec2

    def _eip(self, alloc_id, public_ip, associated=False):
        addr = {"AllocationId": alloc_id, "PublicIp": public_ip, "Tags": []}
        if associated:
            addr["AssociationId"] = "eipassoc-abc123"
        return addr

    def test_flags_unassociated_eip_as_medium_risk(self):
        result = find_unassociated_eips(self._ec2([self._eip("eipalloc-001", "1.2.3.4")]))
        assert len(result) == 1
        assert result[0]["risk"] == "MEDIUM"
        assert result[0]["monthly_waste_usd"] == pytest.approx(3.60)

    def test_associated_eip_not_flagged(self):
        result = find_unassociated_eips(
            self._ec2([self._eip("eipalloc-001", "1.2.3.4", associated=True)])
        )
        assert result == []

    def test_empty_account_returns_empty_list(self):
        assert find_unassociated_eips(self._ec2([])) == []

    def test_two_zombie_eips_total_waste(self):
        eips = [self._eip(f"eipalloc-00{i}", f"1.2.3.{i}") for i in range(2)]
        result = find_unassociated_eips(self._ec2(eips))
        assert len(result) == 2
        assert sum(r["monthly_waste_usd"] for r in result) == pytest.approx(7.20)

    def test_mixed_associated_and_zombie(self):
        addrs = [
            self._eip("eipalloc-001", "1.2.3.1"),                     # zombie
            self._eip("eipalloc-002", "1.2.3.2", associated=True),    # in use
            self._eip("eipalloc-003", "1.2.3.3"),                     # zombie
        ]
        result = find_unassociated_eips(self._ec2(addrs))
        assert len(result) == 2
        assert {r["resource_id"] for r in result} == {"eipalloc-001", "eipalloc-003"}


# ── find_idle_ec2 ─────────────────────────────────────────────────────────────
class TestFindIdleEc2:
    def _clients(self, instances, cpu_avg):
        ec2 = MagicMock()
        pager = MagicMock()
        reservations = [{"Instances": instances}] if instances else []
        pager.paginate.return_value = [{"Reservations": reservations}]
        ec2.get_paginator.return_value = pager

        cw = MagicMock()
        if cpu_avg is None:
            cw.get_metric_statistics.return_value = {"Datapoints": []}
        else:
            cw.get_metric_statistics.return_value = {
                "Datapoints": [{"Average": cpu_avg}]
            }
        return ec2, cw

    def _instance(self, iid, itype="t3.large"):
        return {
            "InstanceId": iid,
            "InstanceType": itype,
            "LaunchTime": _utcnow(),
            "Tags": [{"Key": "Name", "Value": iid}],
        }

    def test_flags_zero_cpu_as_high_risk(self):
        ec2, cw = self._clients([self._instance("i-001")], cpu_avg=None)
        result = find_idle_ec2(ec2, cw)
        assert len(result) == 1
        assert result[0]["risk"] == "HIGH"

    def test_very_low_cpu_flagged_as_medium_risk(self):
        ec2, cw = self._clients([self._instance("i-002")], cpu_avg=3.0)
        result = find_idle_ec2(ec2, cw)
        assert len(result) == 1
        assert result[0]["risk"] == "MEDIUM"

    def test_active_instance_not_flagged(self):
        ec2, cw = self._clients([self._instance("i-003")], cpu_avg=60.0)
        assert find_idle_ec2(ec2, cw) == []

    def test_exactly_at_threshold_not_flagged(self):
        ec2, cw = self._clients([self._instance("i-004")], cpu_avg=5.0)
        assert find_idle_ec2(ec2, cw) == []

    def test_empty_account_returns_empty_list(self):
        ec2, cw = self._clients([], cpu_avg=None)
        assert find_idle_ec2(ec2, cw) == []
