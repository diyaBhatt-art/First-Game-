using System;
using System.Collections.Generic;
using UnityEngine;

namespace MMystery.Core
{
    public class BuckSpawner : MonoBehaviour
    {
        [SerializeField] private GameObject buckPrefab;

        private List<GameObject> activeBucks = new List<GameObject>();

        public event Action<Vector3, int> OnBuckCollected;

        public void TriggerBuckCollected(Vector3 pos, int value)
        {
            OnBuckCollected?.Invoke(pos, value);
        }

        public void SpawnBucks(Bounds[] zones)
        {
            ClearBucks();

            if (zones == null || zones.Length == 0 || buckPrefab == null)
            {
                Debug.LogWarning("BuckSpawner: No zones or buckPrefab configured.");
                return;
            }

            for (int i = 0; i < GameConstants.BUCKS_PER_SPAWN; i++)
            {
                // Pick random zone
                Bounds zone = zones[UnityEngine.Random.Range(0, zones.Length)];

                // Pick random point in XZ within zone, keeping Y at 0.5f
                float rx = UnityEngine.Random.Range(zone.min.x, zone.max.x);
                float rz = UnityEngine.Random.Range(zone.min.z, zone.max.z);
                Vector3 spawnPos = new Vector3(rx, 0.5f, rz);

                // Instantiate and track
                GameObject buck = Instantiate(buckPrefab, spawnPos, Quaternion.identity, transform);
                activeBucks.Add(buck);
            }
        }

        public void ClearBucks()
        {
            foreach (var b in activeBucks)
            {
                if (b != null)
                {
                    Destroy(b);
                }
            }
            activeBucks.Clear();
        }

        public List<Vector3> GetBuckPositions()
        {
            List<Vector3> positions = new List<Vector3>();
            // Filter null references (destroyed pickups)
            activeBucks.RemoveAll(item => item == null);

            foreach (var b in activeBucks)
            {
                if (b != null)
                {
                    positions.Add(b.transform.position);
                }
            }
            return positions;
        }
    }
}
