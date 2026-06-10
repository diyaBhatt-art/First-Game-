using System.Collections.Generic;
using UnityEngine;
using MMystery.Players;

namespace MMystery.Core
{
    public static class RoleAssigner
    {
        public static void AssignRoles(List<PlayerData> players, List<RoleDefinitionSO> allRoles)
        {
            if (players == null || players.Count == 0) return;

            // Find role templates
            RoleDefinitionSO murdererRole = null;
            RoleDefinitionSO sheriffRole = null;
            RoleDefinitionSO innocentRole = null;

            foreach (var r in allRoles)
            {
                if (r.roleId == "murderer") murdererRole = r;
                else if (r.roleId == "sheriff") sheriffRole = r;
                else if (r.roleId == "innocent") innocentRole = r;
            }

            // Fallbacks in case definitions are missing
            if (murdererRole == null) Debug.LogError("RoleAssigner: Murderer role definition missing!");
            if (sheriffRole == null) Debug.LogError("RoleAssigner: Sheriff role definition missing!");
            if (innocentRole == null) Debug.LogError("RoleAssigner: Innocent role definition missing!");

            // Fisher-Yates Shuffle
            List<PlayerData> shuffled = new List<PlayerData>(players);
            int n = shuffled.Count;
            for (int i = n - 1; i > 0; i--)
            {
                int r = Random.Range(0, i + 1);
                PlayerData temp = shuffled[i];
                shuffled[i] = shuffled[r];
                shuffled[r] = temp;
            }

            // Assign exactly 1 Murderer
            shuffled[0].Role = murdererRole;

            // Assign 1 Sheriff if 4+ players, otherwise everyone else is Innocent
            if (players.Count >= 4)
            {
                shuffled[1].Role = sheriffRole;
            }
            else
            {
                shuffled[1].Role = innocentRole;
            }

            for (int i = 2; i < shuffled.Count; i++)
            {
                shuffled[i].Role = innocentRole;
            }

            // Log details
            Debug.Log("========================================");
            Debug.Log("ROLE ASSIGNMENT");
            Debug.Log("========================================");
            foreach (var p in players)
            {
                string tag = p.IsBot ? "BOT" : "HUMAN";
                Debug.Log($"  {p.DisplayName} [{tag}] -> {p.Role?.displayName.ToUpper()}");
            }
            Debug.Log("========================================");
        }
    }
}
