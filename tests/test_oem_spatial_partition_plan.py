"""OSM-derived spatial cell -> authentic SDAL KD index planning contracts."""
from __future__ import annotations

from pathlib import Path
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

    def test_two_osm_features_in_disjoint_cells_generate_real_index(self):
        features=(Footprint(11,1,0,512,512,1000,1000),
                  Footprint(21,0,0,7000,7000,7500,7500))
        plan=plan_spatial_partition(self.region,features,
                                    max_features_per_leaf=1)
        self.assertIsInstance(plan,Split)
        self.assertEqual(plan.axis,"longitude")
        self.assertEqual(plan.cut_32nds,16)
        leaves=leaf_inventory(plan)
        self.assertEqual(set(leaves),{"L","R"})
        refs={"L":(SpatialRef(1,0,0x18000020),),
              "R":(SpatialRef(0,0,0x18000040),)}
        raw=compile_planned_index(plan,parcel_refs=refs,
                                  entity_id_bounds={"":(1,1)})
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

    def test_complete_two_level_kd_tree_and_local_offsets(self):
        features=[]
        for i,(x,y) in enumerate(((500,500),(500,7000),(7000,500),(7000,7000))):
            features.append(Footprint(i,1,0,x,y,x+100,y+100))
        tree=plan_spatial_partition(self.region,features,
                                    max_features_per_leaf=1)
        leaves=leaf_inventory(tree)
        self.assertEqual(set(leaves),{"LL","LR","RL","RR"})
        refs={path:(SpatialRef(1,0,0x18000020+0x20*i),)
              for i,path in enumerate(sorted(leaves))}
        raw=compile_planned_index(tree,parcel_refs=refs,entity_id_bounds={})
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

    def test_crossing_osm_road_must_be_clipped_before_partition(self):
        road=Footprint(123,0,0,0,0,8192,8192)
        poi=Footprint(99,1,0,512,512,520,520)
        with self.assertRaisesRegex(SpatialPlanError,"clipping"):
            plan_spatial_partition(self.region,(road,poi),
                                   max_features_per_leaf=1)

    def test_input_stable_under_feature_reordering(self):
        feats=[Footprint(8,1,0,500,500,600,600),
               Footprint(1,1,0,7000,7000,7200,7200)]
        a=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        b=plan_spatial_partition(self.region,reversed(feats),
                                 max_features_per_leaf=1)
        self.assertEqual(a,b)

    def test_no_unchecked_routing_entity_id_minima(self):
        feats=(Footprint(1,0,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        ref={"L":(SpatialRef(0,0,0x18000020),),
             "R":(SpatialRef(1,0,0x18000040),)}
        with self.assertRaisesRegex(SpatialPlanError,"segment/node ID minima"):
            compile_planned_index(tree,parcel_refs=ref,entity_id_bounds={})

    def test_reject_wrong_type_and_reused_physical_pid(self):
        feats=(Footprint(1,0,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        with self.assertRaisesRegex(SpatialPlanError,"type/layer"):
            compile_planned_index(tree,
                parcel_refs={"L":(SpatialRef(1,0,0x18000020),),
                             "R":(SpatialRef(1,0,0x18000040),)},
                entity_id_bounds={"":(1,1)})
        with self.assertRaisesRegex(SpatialPlanError,"reused"):
            compile_planned_index(tree,
                parcel_refs={"L":(SpatialRef(0,0,0x18000020),),
                             "R":(SpatialRef(1,0,0x18000020),)},
                entity_id_bounds={"":(1,1)})

    def test_missing_reference_and_external_handle_refused(self):
        feats=(Footprint(1,1,0,500,500,600,600),
               Footprint(2,1,0,7000,7000,7200,7200))
        tree=plan_spatial_partition(self.region,feats,max_features_per_leaf=1)
        with self.assertRaisesRegex(SpatialPlanError,"Every terminal"):
            compile_planned_index(tree,parcel_refs={},entity_id_bounds={})
        with self.assertRaisesRegex(SpatialPlanError,"External"):
            compile_planned_index(tree,
              parcel_refs={"L":(SpatialRef(1,0,0x98000020),),
                           "R":(SpatialRef(1,0,0x18000040),)},
              entity_id_bounds={})

    def test_single_leaf_and_small_tile_are_not_guessed(self):
        f=Footprint(1,1,0,600,600,700,700)
        p=plan_spatial_partition(self.region,(f,))
        self.assertIsInstance(p,Leaf)
        with self.assertRaisesRegex(SpatialPlanError,"Single-leaf"):
            compile_planned_index(p,
                parcel_refs={"":(SpatialRef(1,0,0x18000020),)},
                entity_id_bounds={})
        with self.assertRaisesRegex(SpatialPlanError,"smaller"):
            plan_spatial_partition(Rect(0,0,128,128),
                                   (Footprint(2,1,0,1,1,2,2),))

    def test_ntu_conversion_uses_actual_sdal_scale(self):
        x=feature_from_osm_bounds(10,1,0,(33.2,34.4,33.3,34.5))
        self.assertEqual((x.west,x.south,x.east,x.north),
                         (3320000,3440000,3330000,3450000))

    def test_bad_depth_coordinates_and_duplicate_source_rejected(self):
        f=Footprint(1,1,0,100,100,200,200)
        with self.assertRaises(SpatialPlanError):
            Rect(0,0,0,5)
        with self.assertRaises(SpatialPlanError):
            plan_spatial_partition(self.region,(f,f))
        with self.assertRaises(SpatialPlanError):
            plan_spatial_partition(self.region,(f,),max_features_per_leaf=0)


if __name__=="__main__":
    unittest.main()
