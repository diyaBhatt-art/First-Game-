using UnityEngine;

namespace MMystery.Core
{
    [CreateAssetMenu(fileName = "NewBotPersonality", menuName = "M Mystery/Bot Personality")]
    public class BotPersonalitySO : ScriptableObject
    {
        [Header("Personality Identification")]
        public string personalityId;

        [Header("Behavioral Weights (0 to 1)")]
        [Range(0f, 1f)] public float aggression;
        [Range(0f, 1f)] public float caution;
        [Range(0f, 1f)] public float greed;
        [Range(0f, 1f)] public float accuracy;
    }
}
