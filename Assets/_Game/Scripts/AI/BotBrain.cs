using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using MMystery.Core;
using MMystery.Players;

namespace MMystery.AI
{
    public class BotBrain
    {
        public BotPersonalitySO personality;
        public float suspicionLevel = 0f;       // 0-1, increases when witnessing deaths
        public string suspectedMurdererID = null;
        public float lastSeenMurdererX;
        public float lastSeenMurdererZ;

        public bool hasSuspicion => suspicionLevel > 0.4f;

        // Score each possible action and return best move target
        public Vector3 ChooseTarget(
            PlayerData self,
            List<PlayerData> allPlayers,
            Vector3 droppedGunPos,    // Vector3.negativeInfinity if no gun
            List<Vector3> buckPositions)
        {
            // Utility scores (higher = do this)
            float fleeScore = 0f;
            float chaseScore = 0f;
            float gunScore = 0f;
            float buckScore = 0f;

            // Find nearest murderer (only if we know their identity)
            PlayerData knownMurderer = hasSuspicion
                ? allPlayers.FirstOrDefault(p => p.PlayerId == suspectedMurdererID)
                : null;

            // Flee logic (innocent/sheriff fleeing murderer)
            if (self.Role?.roleId != "murderer" && knownMurderer != null)
            {
                float d = DistanceTo(self, knownMurderer);
                fleeScore = (1f - d / 30f) * personality.caution * 2f;
            }

            // Chase logic (murderer hunting targets)
            if (self.Role?.roleId == "murderer")
            {
                PlayerData nearest = NearestAliveNonSelf(self, allPlayers);
                if (nearest != null)
                {
                    chaseScore = personality.aggression * 3f;
                }
            }

            // Gun pickup logic
            if (droppedGunPos != Vector3.negativeInfinity && (self.Role == null || !self.Role.hasGun))
            {
                float d = Vector3.Distance(new Vector3(self.Position.x, 0f, self.Position.z), droppedGunPos);
                gunScore = (1f - d / 20f) * 2f;
            }

            // Buck collection logic
            if (buckPositions != null && buckPositions.Count > 0 && self.MBucksThisRound < GameConstants.MAX_BUCKS_PER_ROUND)
            {
                buckScore = personality.greed * 1.5f;
            }

            // Return target position based on highest score
            if (chaseScore > fleeScore && chaseScore > gunScore && chaseScore > buckScore)
            {
                PlayerData target = NearestAliveNonSelf(self, allPlayers);
                return target != null ? target.Position : self.Position;
            }

            if (fleeScore >= chaseScore && fleeScore > gunScore)
            {
                if (knownMurderer != null)
                {
                    Vector3 fleeDir = (self.Position - knownMurderer.Position).normalized;
                    fleeDir.y = 0f; // horizontal only
                    return self.Position + fleeDir * 8f;
                }
            }

            if (gunScore > buckScore)
            {
                return droppedGunPos;
            }

            if (buckPositions != null && buckPositions.Count > 0)
            {
                return NearestBuck(self.Position, buckPositions);
            }

            // Wander target as default
            Vector3 wanderOffset = Random.insideUnitSphere * 3f;
            wanderOffset.y = 0f;
            return self.Position + wanderOffset;
        }

        public void OnWitnessedDeath(PlayerData suspected)
        {
            if (suspected == null) return;
            suspicionLevel = Mathf.Min(1f, suspicionLevel + 0.6f);
            suspectedMurdererID = suspected.PlayerId;
            lastSeenMurdererX = suspected.Position.x;
            lastSeenMurdererZ = suspected.Position.z;
        }

        public void ResetForRound()
        {
            suspicionLevel = 0f;
            suspectedMurdererID = null;
        }

        private Vector3 NearestBuck(Vector3 from, List<Vector3> bucks)
        {
            if (bucks == null || bucks.Count == 0) return from;
            return bucks.OrderBy(b => Vector3.Distance(from, b)).First();
        }

        private PlayerData NearestAliveNonSelf(PlayerData self, List<PlayerData> all)
        {
            if (all == null) return null;
            return all.Where(p => p.PlayerId != self.PlayerId && p.IsAlive)
                      .OrderBy(p => Vector3.Distance(self.Position, p.Position))
                      .FirstOrDefault();
        }

        private float DistanceTo(PlayerData a, PlayerData b)
        {
            return Vector3.Distance(a.Position, b.Position);
        }
    }
}
