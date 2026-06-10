using System.Text;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using TMPro;
using Unity.Netcode;
using MMystery.Networking;
using MMystery.Core;
using MMystery.Players;

namespace MMystery.UI
{
    public class RoundEndScreen : MonoBehaviour
    {
        [Header("UI Canvas Panels")]
        [SerializeField] private GameObject screenOverlay;
        [SerializeField] private TMP_Text resultTitleText;
        [SerializeField] private TMP_Text scoreboardText;

        [Header("Scoreboard Actions")]
        [SerializeField] private Button playAgainButton;
        [SerializeField] private Button backToLobbyButton;

        private void Start()
        {
            if (playAgainButton != null)
            {
                playAgainButton.onClick.AddListener(OnPlayAgainClicked);
            }

            if (backToLobbyButton != null)
            {
                backToLobbyButton.onClick.AddListener(OnBackToLobbyClicked);
            }

            // Hide initially
            if (screenOverlay != null)
            {
                screenOverlay.SetActive(false);
            }
        }

        private void OnEnable()
        {
            GameManager.OnRoundEnded += DisplayEndScreen;
        }

        private void OnDisable()
        {
            GameManager.OnRoundEnded -= DisplayEndScreen;
        }

        public void DisplayEndScreen(string winner)
        {
            if (screenOverlay == null) return;

            screenOverlay.SetActive(true);

            // Unlock local mouse cursor to interact with buttons
            var tpc = Camera.main?.GetComponent<ThirdPersonCamera>();
            if (tpc != null)
            {
                tpc.LockCursor(false);
            }

            // 1. Render Winner Title Banner
            if (winner == "murderer")
            {
                resultTitleText.text = "MURDERER WINS";
                resultTitleText.color = new Color(0.898f, 0.192f, 0.439f); // #E53170 Murderer Red
            }
            else
            {
                resultTitleText.text = "INNOCENTS WIN";
                resultTitleText.color = new Color(0.173f, 0.71f, 0.91f);  // #2CB5E8 Innocent Cyan
            }

            // 2. Render Scoreboard Listing
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("SCOREBOARD:\n");

            // Look up all players in active scene
            foreach (var pc in GameObject.FindObjectsOfType<PlayerController>())
            {
                if (pc.data != null)
                {
                    PlayerData d = pc.data;
                    string rName = d.Role != null ? d.Role.displayName.ToUpper() : "UNKNOWN";
                    string rColorHex = d.Role != null ? ColorUtility.ToHtmlStringRGB(d.Role.roleColor) : "FFFFFF";
                    string status = d.IsAlive ? "<color=#32D25A>ALIVE</color>" : "<color=#FF3B30>DEAD</color>";

                    sb.AppendLine($"{d.DisplayName}  —  <color=#{rColorHex}>{rName}</color>  —  M Bucks: {d.MBucksThisRound}  —  {status}");
                }
            }

            scoreboardText.text = sb.ToString();

            // 3. Play Again permissions checks (Only the Host can restart, clients see button disabled)
            bool isHost = true;
            if (NetworkManager.Singleton != null && NetworkManager.Singleton.IsListening)
            {
                isHost = NetworkManager.Singleton.IsServer;
            }

            if (playAgainButton != null)
            {
                playAgainButton.gameObject.SetActive(isHost);
            }
        }

        private void OnPlayAgainClicked()
        {
            if (GameManager.Instance != null && GameManager.Instance.IsServer)
            {
                screenOverlay.SetActive(false);
                GameManager.Instance.BeginRoundServerRpc();
            }
        }

        private void OnBackToLobbyClicked()
        {
            screenOverlay.SetActive(false);
            
            // Clean up connections
            if (NetworkSession.Instance != null)
            {
                NetworkSession.Instance.Disconnect();
            }

            // Re-load the main Menu scene
            SceneManager.LoadScene("Menu");
        }
    }
}
