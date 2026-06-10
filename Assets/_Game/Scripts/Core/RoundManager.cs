using System;
using System.Collections.Generic;
using UnityEngine;
using MMystery.Players;

namespace MMystery.Core
{
    public class RoundManager : MonoBehaviour
    {
        public float remainingTime = GameConstants.ROUND_DURATION;
        public bool isRunning = false;

        public event Action<string> OnRoundEnd; // Fires with "murderer" or "innocents"

        private List<PlayerData> _players = new List<PlayerData>();

        public void SetPlayersList(List<PlayerData> players)
        {
            _players = players;
        }

        public void StartRound()
        {
            remainingTime = GameConstants.ROUND_DURATION;
            isRunning = true;
        }

        private void Update()
        {
            if (!isRunning) return;

            remainingTime -= Time.deltaTime;
            if (remainingTime <= 0f)
            {
                remainingTime = 0f;
            }

            // In server-authoritative netcode or local game loops, check win conditions
            CheckWinConditions(_players);
        }

        public void CheckWinConditions(List<PlayerData> players)
        {
            if (!isRunning || players == null || players.Count == 0) return;

            bool murdererAlive = false;
            bool nonMurdererAlive = false;

            foreach (var p in players)
            {
                if (p.Role == null) continue;

                if (p.Role.roleId == "murderer" && p.IsAlive)
                {
                    murdererAlive = true;
                }
                else if (p.Role.roleId != "murderer" && p.IsAlive)
                {
                    nonMurdererAlive = true;
                }
            }

            // 1. Murderer killed everyone -> Murderer wins
            if (murdererAlive && !nonMurdererAlive)
            {
                EndRound("murderer");
            }
            // 2. Murderer is dead -> Innocents win
            else if (!murdererAlive)
            {
                EndRound("innocents");
            }
            // 3. Timer expired and at least one Innocent/Sheriff is alive -> Innocents win
            else if (remainingTime <= 0f && nonMurdererAlive)
            {
                EndRound("innocents");
            }
        }

        public void EndRound(string winner)
        {
            isRunning = false;
            OnRoundEnd?.Invoke(winner);
        }

        public string GetTimeString()
        {
            int minutes = Mathf.FloorToInt(remainingTime / 60f);
            int seconds = Mathf.FloorToInt(remainingTime % 60f);
            return $"{minutes}:{seconds:00}";
        }
    }
}
