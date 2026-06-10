using UnityEngine;

namespace MMystery.Core
{
    [CreateAssetMenu(fileName = "NewRoleDefinition", menuName = "M Mystery/Role Definition")]
    public class RoleDefinitionSO : ScriptableObject
    {
        [Header("Role Identification")]
        public string roleId;
        public string displayName;
        public Color roleColor;

        [Header("Role Capabilities")]
        public bool hasKnife;
        public bool hasGun;
        public bool canKill;
    }
}
