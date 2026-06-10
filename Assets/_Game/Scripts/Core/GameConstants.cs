namespace MMystery.Core
{
    public static class GameConstants
    {
        public const float ROUND_DURATION = 180f;
        public const float KNIFE_RANGE = 2.5f;      // world units
        public const float GUN_RANGE = 40f;          // world units
        public const float BUCK_COLLECT_RANGE = 1.0f;
        public const int MAX_BUCKS_PER_ROUND = 50;
        public const int BUCKS_PER_SPAWN = 20;
        public const float WALK_SPEED = 4f;
        public const float SPRINT_SPEED = 7f;
        public const float STAMINA_MAX = 100f;
        public const float STAMINA_DRAIN = 25f;     // per second sprinting
        public const float STAMINA_REGEN = 15f;     // per second not sprinting
        public const float BULLET_SPEED = 25f;       // world units/sec
    }
}
