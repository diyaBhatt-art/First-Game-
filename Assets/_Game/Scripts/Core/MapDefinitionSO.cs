using UnityEngine;

namespace MMystery.Core
{
    [CreateAssetMenu(fileName = "NewMapDefinition", menuName = "M Mystery/Map Definition")]
    public class MapDefinitionSO : ScriptableObject
    {
        [Header("Map Details")]
        public string mapId;
        public string displayName;
        public string sceneName;

        [Header("Spawns & Zones")]
        public Vector3[] spawnPoints;
        public Bounds[] buckSpawnZones;
    }
}
