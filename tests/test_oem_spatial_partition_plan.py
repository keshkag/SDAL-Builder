"""OSM-derived spatial cell -> physical SDAL KD and ParcelID contracts."""
from __future__ import annotations

import io
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from sdal_builder.osm_spatial_plan import (
    Rect,Footprint,Leaf,Split,SpatialPlanError,
    plan_spatial_partition,leaf_inventory,compile_planned_index,
    feature_from_osm_bounds,
)
from sdal_builder.oem_kd_codec import SpatialRef,decode_kd_node
from sdal_builder.oem_index import decode_index_parcel


class SpatialPlanTests(unittest.TestCase):
    def setUp(self):
        self.region=Rect(0,0,8192,8192)

    def targets(self,by_leaf:dict) -> io.BytesIO:
        """Synthetic PHYSICAL parcel file, headers already positioned."""
        refs=[ref for entry in by_leaf.values() for ref in entry]
        maximum=max(((ref.parcel_id&0xffffff)*256+20 for ref in refs),default=32)
        contents=bytearray(maximum)
        placed=set()
        for ref in refs:
            pid=ref.parcel_id
            if pid in placed:
                continue
            placed.add(pid)
            at=(pid&0xffffff)*256
            struct.pack_into(">IHBBBBHHHHH",contents,at,pid,0,
                             ref.parcel_type,1,0,0,0,0,0,0,0)
        return io.BytesIO(contents)

    def test_two_osm_features_build_true_kd_index(self):
        features=(Footprint(11,1,0,512,512,1000,1000),
                  Footprint(21,0,0,7000,7000,7500,7500))
        plan=plan_spatial_partition(self.region,features,max_features_per_leaf=1)
        self.assertIsInstance(plan,Split)
        self.assertEqual((plan.axis,plan.cut_32nds),("longitude",16))
        self.assertEqual(set(leaf_inventory(plan)),{"L","R"})
        refs={"L":(SpatialRef(1,0,0x18000020),),
              "R":(SpatialRef(0,0,0x18000040),)}
        raw=compile_planned_index(plan,parcel_refs=refs,
                                  entity_id_bounds={"":(1,1)},
                                  target_file=self.targets(refs))
        parsed=decode_index_parcel(raw,absolute_offset=0xC200)
        self.assertEqual(parsed.reassemble(),raw)
        root,end=decode_kd_node(raw,parsed.root_offsets[0],len(raw))
        self.assertEqual(len(raw),0x5000)
        self.assertFalse(root.horizontal_cut)
        self.assertEqual(root.left_parcels,refs["L"])
        self.assertEqual(root.right_parcels,refs["R"])
        self.assertEqual(root.entity_ids,(1,1))
        self.assertEqual(root.cut_32nds,16)
        self.assertIsNone(root.left_child)
        self.assertIsNone(root.right_child)

    def test_two_level_kd_tree_and_local_offsets(self):
        features=tuple(Footprint(i,1,0,x,y,x+100,y+100)
                       for i,(x,y) in enumerate(
                           ((500,500),(500,7000),(7000,500),(7000,7000))))
        tree=plan_spatial_partition(self.region,features,max_features_per_leaf=1)
        leaves=leaf_inventory(tree)
        self.assertEqual(set(leaves),{"LL","LR","RL","RR"})
        refs={path:(SpatialRef(1,0,0x18000020+0x20*i),)
              for i,path in enumerate(sorted(leaves))}
        raw=compile_planned_index(tree,parcel_refs=refs,
                                  entity_id_bounds={},
                                  target_file=self.targets(refs))
        idx=decode_index_parcel(raw,absolute_offset=0xC200)
        at=idx.root_offsets[0]
        parent, at1=decode_kd_node(raw,at,len(raw))
        self.assertEqual(parent.left_child.mode,3)
        self.assertEqual(parent.right_child.mode,3)
        l_at=at+2*parent.left_child.value
        r_at=at+2*parent.right_child.value
        self.assertEqual(l_at,at1)
        left, left_end=decode_kd_node(raw,l_at,len(raw))
        right, right_end=decode_kd_node(raw,r_at,len(raw))
        self.assertEqual(left_end,r_at)
        self.assertGreater(right_end,r_at)
        self.assertTrue(left.horizontal_cut)
        self.assertTrue(right.horizontal_cut)

    def test_crossing_osm_road_requires_real_clipping(self):
        road=Footprint(123,0,0,0,0,8192,8192)
        poi=Footprint(99,1,0,512,512,520,520)
        with self.assertRaisesRegex(SpatialPlanError,"clipping"):
            plan_spatial_partition(self.region,(road,poi),max_features_per_leaf=1)

    def test_feature_order_does_not_change_plan(self):
        feats=[Footprint(8,1,0,500,500,600,600),
               Footprint(1,1,0,7000,7000,7200,7200)]
        self.assertEqual(
            plan_spatial_partition(self.region,feats,max_features_per_leaf=1),
            plan_spatial_partition(self.region,reversed(feats),
                                   max_features_per_leaf=1))

    def test_routing_split_requires_explicit_minima(self):
        feats=(Footprint(1,0,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        refs={"L":(SpatialRef(0,0,0x18000020),),
              "R":(SpatialRef(1,0,0x18000040),)}
        with self.assertRaisesRegex(SpatialPlanError,"segment/node ID minima"):
            compile_planned_index(tree,parcel_refs=refs,entity_id_bounds={},
                                  target_file=self.targets(refs))

    def test_mismatched_types_and_duplicate_pids_fail(self):
        feats=(Footprint(1,0,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        wrong={"L":(SpatialRef(1,0,0x18000020),),
               "R":(SpatialRef(1,0,0x18000040),)}
        with self.assertRaisesRegex(SpatialPlanError,"type/layer"):
            compile_planned_index(tree,parcel_refs=wrong,
                entity_id_bounds={"":(1,1)},target_file=self.targets(wrong))
        repeated={"L":(SpatialRef(0,0,0x18000020),),
                  "R":(SpatialRef(1,0,0x18000020),)}
        with self.assertRaisesRegex(SpatialPlanError,"reused"):
            compile_planned_index(tree,parcel_refs=repeated,
                entity_id_bounds={"":(1,1)},target_file=self.targets(repeated))

    def test_missing_or_external_targets_fail(self):
        feats=(Footprint(1,1,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        with self.assertRaisesRegex(SpatialPlanError,"Every terminal"):
            compile_planned_index(tree,parcel_refs={},entity_id_bounds={},
                                  target_file=self.targets({}))
        external={"L":(SpatialRef(1,0,0x98000020),),
                  "R":(SpatialRef(1,0,0x18000040),)}
        with self.assertRaisesRegex(SpatialPlanError,"External"):
            compile_planned_index(tree,parcel_refs=external,entity_id_bounds={},
                                  target_file=self.targets(external))

    def test_missing_physical_file_or_wrong_target_type_fails(self):
        feats=(Footprint(1,1,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        refs={"L":(SpatialRef(1,0,0x18000020),),
              "R":(SpatialRef(1,0,0x18000040),)}
        with self.assertRaisesRegex(SpatialPlanError,"Existing physical"):
            compile_planned_index(tree,parcel_refs=refs,
                                  entity_id_bounds={},target_file=None)
        fd=self.targets(refs)
        fd.seek(0x2000+6)
        fd.write(b"\x00")
        with self.assertRaisesRegex(SpatialPlanError,"target_type_mismatch"):
            compile_planned_index(tree,parcel_refs=refs,
                                  entity_id_bounds={},target_file=fd)

    def test_single_leaf_and_minimum_cell_are_not_guessed(self):
        f=Footprint(1,1,0,600,600,700,700)
        p=plan_spatial_partition(self.region,(f,))
        self.assertIsInstance(p,Leaf)
        refs={"":(SpatialRef(1,0,0x18000020),)}
        with self.assertRaisesRegex(SpatialPlanError,"Single-leaf"):
            compile_planned_index(p,parcel_refs=refs,entity_id_bounds={},
                                  target_file=self.targets(refs))
        with self.assertRaisesRegex(SpatialPlanError,"smaller"):
            plan_spatial_partition(Rect(0,0,128,128),
                                   (Footprint(2,1,0,1,1,2,2),))

    def test_ntu_conversion_uses_1_per_100000_degree(self):
        x=feature_from_osm_bounds(10,1,0,(33.2,34.4,33.3,34.5))
        self.assertEqual((x.west,x.south,x.east,x.north),
                         (3320000,3440000,3330000,3450000))

    def test_invalid_coordinates_or_duplicate_sources_rejected(self):
        f=Footprint(1,1,0,100,100,200,200)
        with self.assertRaises(SpatialPlanError):
            Rect(0,0,0,5)
        with self.assertRaises(SpatialPlanError):
            plan_spatial_partition(self.region,(f,f))
        with self.assertRaises(SpatialPlanError):
            plan_spatial_partition(self.region,(f,),max_features_per_leaf=0)


if __name__=="__main__":
    unittest.main()
