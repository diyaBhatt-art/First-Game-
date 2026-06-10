using UnityEngine;

namespace MMystery.Core
{
    public enum ItemEffectType
    {
        Footprints,
        Tracker,
        AuraScan,
        ShadowBlade,
        GhostMode,
        DeadEye,
        NoiseTrap,
        Alarm
    }

    [CreateAssetMenu(fileName = "NewItemDefinition", menuName = "M Mystery/Item Definition")]
    public class ItemDefinitionSO : ScriptableObject
    {
        [Header("Item Information")]
        public string itemId;
        public string displayName;
        [TextArea(2, 5)]
        public string description;

        [Header("Item Properties")]
        public int cost;
        public float effectDuration;
        public ItemEffectType effectType;
    }
}
