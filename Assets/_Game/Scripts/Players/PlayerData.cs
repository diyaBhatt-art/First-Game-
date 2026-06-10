using UnityEngine;
using MMystery.Core;

namespace MMystery.Players
{
    public class PlayerData
    {
        public string PlayerId;
        public string DisplayName;
        public RoleDefinitionSO Role;
        public bool IsAlive = true;
        public bool IsBot = false;
        public float Stamina = GameConstants.STAMINA_MAX;
        public int MBucksThisRound = 0;
        public int AttackCooldownFrames = 0;
        public Vector3 Position;
        public Vector2 FacingDirection;
        public bool IsMoving = false;
        public float AnimPhase = 0f;
    }
}
