using UnityEngine;
using UnityEngine.UI;
using TMPro;
using Unity.Netcode;
using MMystery.Core;
using MMystery.Players;
using MMystery.Networking;

namespace MMystery.UI
{
    public class HUD : MonoBehaviour
    {
        [Header("HUD Text Elements")]
        [SerializeField] private TMP_Text timerText;
        [SerializeField] private TMP_Text roleText;
        [SerializeField] private TMP_Text buckText;
        [SerializeField] private TMP_Text aliveText;

        [Header("Stamina Slider Elements")]
        [SerializeField] private Image staminaBarBG;
        [SerializeField] private Image staminaBarFill;
        [SerializeField] private TMP_Text staminaLabel;

        [Header("Crosshair Elements")]
        [SerializeField] private Image crosshairHorizontal;
        [SerializeField] private Image crosshairVertical;

        private PlayerController localPlayer;
        private RoundManager roundManager;

        private void Start()
        {
            roundManager = GameObject.FindObjectOfType<RoundManager>();
            
            // Check crosshair configuration
            if (staminaLabel != null && staminaLabel.text == "")
            {
                staminaLabel.text = "STAMINA";
            }
        }

        private void Update()
        {
            // 1. Find local player if not cached yet
            if (localPlayer == null)
            {
                FindLocalPlayer();
            }

            // 2. Update Round Clock
            if (roundManager != null)
            {
                float t = roundManager.remainingTime;
                timerText.text = roundManager.GetTimeString();
                
                // Color shift when timer under 30 seconds
                timerText.color = (t < 30f) ? new Color(1f, 0.24f, 0.24f) : Color.white;
            }

            // 3. Update local player status (role card, collected bucks, and stamina meter)
            if (localPlayer != null && localPlayer.data != null)
            {
                PlayerData data = localPlayer.data;

                // Role text mapping
                if (data.Role != null)
                {
                    roleText.text = data.Role.displayName.ToUpper();
                    roleText.color = data.Role.roleColor;
                }
                else
                {
                    roleText.text = "SELECTING ROLE...";
                    roleText.color = Color.white;
                }

                // Bucks wallet text
                buckText.text = $"M BUCKS: {data.MBucksThisRound}/{GameConstants.MAX_BUCKS_PER_ROUND}";

                // Stamina bar updates
                float staminaPct = data.Stamina / GameConstants.STAMINA_MAX;
                if (staminaBarFill != null)
                {
                    staminaBarFill.fillAmount = staminaPct;

                    // Color shifts based on exhaustion
                    if (staminaPct > 0.6f)
                    {
                        staminaBarFill.color = new Color(0.196f, 0.824f, 0.353f); // #32D25A Success Green
                    }
                    else if (staminaPct > 0.3f)
                    {
                        staminaBarFill.color = new Color(0.862f, 0.8f, 0.196f);  // #DCCC32 Warn Yellow
                    }
                    else
                    {
                        staminaBarFill.color = new Color(0.862f, 0.274f, 0.196f); // #DC4632 Alert Red
                    }
                }
            }

            // 4. Update alive counter (total of connected players + bots that are currently alive)
            UpdateAliveCountDisplay();
        }

        private void FindLocalPlayer()
        {
            if (NetworkManager.Singleton != null && NetworkManager.Singleton.IsListening)
            {
                // Networked Local Client
                if (NetworkManager.Singleton.LocalClient != null && NetworkManager.Singleton.LocalClient.PlayerObject != null)
                {
                    localPlayer = NetworkManager.Singleton.LocalClient.PlayerObject.GetComponent<PlayerController>();
                }
            }
            else
            {
                // Local Editor Singleplayer fallback
                foreach (var pc in GameObject.FindObjectsOfType<PlayerController>())
                {
                    if (pc.data != null && !pc.data.IsBot)
                    {
                        localPlayer = pc;
                        break;
                    }
                }
            }
        }

        private void UpdateAliveCountDisplay()
        {
            int totalPlayers = 0;
            int alivePlayers = 0;

            // Search in active scene
            foreach (var pc in GameObject.FindObjectsOfType<PlayerController>())
            {
                if (pc.data != null)
                {
                    totalPlayers++;
                    if (pc.data.IsAlive)
                    {
                        alivePlayers++;
                    }
                }
            }

            // Fallback default target 4 players
            if (totalPlayers == 0) totalPlayers = 4;
            if (alivePlayers == 0) alivePlayers = totalPlayers;

            aliveText.text = $"ALIVE: {alivePlayers}/{totalPlayers}";
        }
    }
}
