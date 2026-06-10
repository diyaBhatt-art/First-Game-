using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using Unity.Netcode;
using MMystery.Networking;

namespace MMystery.UI
{
    public class LobbyUI : MonoBehaviour
    {
        [Header("Menu Panels")]
        [SerializeField] private GameObject mainMenuPanel;
        [SerializeField] private GameObject lobbyPanel;

        [Header("Main Menu Controls")]
        [SerializeField] private Button hostButton;
        [SerializeField] private Button joinButton;
        [SerializeField] private TMP_InputField joinCodeInput;
        [SerializeField] private TMP_Text statusText;

        [Header("Lobby Controls")]
        [SerializeField] private TMP_Text joinCodeDisplay;
        [SerializeField] private Button copyCodeButton;
        [SerializeField] private TMP_Text playerListText;
        [SerializeField] private Button startGameButton;
        [SerializeField] private Button disconnectButton;

        private void Start()
        {
            // Set up button listeners
            hostButton.onClick.AddListener(OnHostClicked);
            joinButton.onClick.AddListener(OnJoinClicked);
            startGameButton.onClick.AddListener(OnStartGame);
            
            if (copyCodeButton != null)
            {
                copyCodeButton.onClick.AddListener(OnCopyCodeClicked);
            }
            if (disconnectButton != null)
            {
                disconnectButton.onClick.AddListener(OnDisconnectClicked);
            }

            joinCodeInput.characterValidation = TMP_InputField.CharacterValidation.Alphanumeric;
            joinCodeInput.characterLimit = 6;
            
            startGameButton.gameObject.SetActive(false);
            ShowMainMenu();
        }

        private void OnDestroy()
        {
            StopAllCoroutines();
        }

        private void ShowMainMenu()
        {
            mainMenuPanel.SetActive(true);
            lobbyPanel.SetActive(false);
            statusText.text = "";
        }

        private async void OnHostClicked()
        {
            statusText.text = "Creating session...";
            hostButton.interactable = false;
            joinButton.interactable = false;

            try
            {
                string code = await NetworkSession.Instance.HostGame();
                
                joinCodeDisplay.text = $"CODE: {code}";
                
                mainMenuPanel.SetActive(false);
                lobbyPanel.SetActive(true);
                
                // Only host sees Start button, and only when enough players (or bot fillers exist)
                startGameButton.gameObject.SetActive(true);
                startGameButton.interactable = true;

                StartCoroutine(LobbyHeartbeatLoop());
                StartCoroutine(PlayerListUpdateLoop());
            }
            catch (Exception e)
            {
                statusText.text = $"Failed: {e.Message}";
                hostButton.interactable = true;
                joinButton.interactable = true;
            }
        }

        private async void OnJoinClicked()
        {
            string code = joinCodeInput.text.ToUpper().Trim();
            if (code.Length != 6)
            {
                statusText.text = "Code must be 6 characters";
                return;
            }

            statusText.text = "Joining...";
            hostButton.interactable = false;
            joinButton.interactable = false;

            try
            {
                await NetworkSession.Instance.JoinGame(code);
                
                joinCodeDisplay.text = $"CODE: {code}";
                mainMenuPanel.SetActive(false);
                lobbyPanel.SetActive(true);
                
                startGameButton.gameObject.SetActive(false); // clients can't start

                StartCoroutine(PlayerListUpdateLoop());
            }
            catch (Exception e)
            {
                statusText.text = $"Could not join: {e.Message}";
                hostButton.interactable = true;
                joinButton.interactable = true;
            }
        }

        private void OnCopyCodeClicked()
        {
            string code = NetworkSession.Instance.JoinCode;
            if (!string.IsNullOrEmpty(code))
            {
                GUIUtility.systemCopyBuffer = code;
                Debug.Log($"LobbyUI: Copied code '{code}' to clipboard!");
            }
        }

        private void OnDisconnectClicked()
        {
            StopAllCoroutines();
            NetworkSession.Instance.Disconnect();
            ShowMainMenu();
            hostButton.interactable = true;
            joinButton.interactable = true;
        }

        private void OnStartGame()
        {
            // Call authoritative server/host GameManager to initiate the round
            if (GameManager.Instance != null)
            {
                GameManager.Instance.BeginRoundServerRpc();
                gameObject.SetActive(false); // Hide Lobby UI upon round commencement
            }
        }

        private IEnumerator LobbyHeartbeatLoop()
        {
            while (NetworkSession.Instance.IsHost && NetworkSession.Instance.CurrentLobby != null)
            {
                var task = NetworkSession.Instance.SendLobbyHeartbeat(NetworkSession.Instance.CurrentLobby.Id);
                yield return new WaitUntil(() => task.IsCompleted);
                yield return new WaitForSeconds(15f);
            }
        }

        private IEnumerator PlayerListUpdateLoop()
        {
            while (NetworkManager.Singleton != null && NetworkManager.Singleton.IsListening)
            {
                UpdatePlayerListDisplay();
                yield return new WaitForSeconds(1.5f);
            }
        }

        private void UpdatePlayerListDisplay()
        {
            if (NetworkManager.Singleton == null || !NetworkManager.Singleton.IsListening) return;

            StringBuilder sb = new StringBuilder();
            sb.AppendLine("PLAYERS IN LOBBY:");

            int pIndex = 1;
            foreach (var client in NetworkManager.Singleton.ConnectedClientsList)
            {
                string pName = "Player " + client.ClientId;
                // Try to find if PlayerObject is spawned and read from it
                if (client.PlayerObject != null)
                {
                    var pc = client.PlayerObject.GetComponent<PlayerController>();
                    if (pc != null && pc.data != null)
                    {
                        pName = pc.data.DisplayName;
                    }
                }

                string dotColor = (client.ClientId == NetworkManager.Singleton.LocalClientId) ? "#00C8FF" : "#FFFFFF";
                sb.AppendLine($"<color={dotColor}>●</color> {pName} {(client.ClientId == NetworkManager.Singleton.ServerClientId ? "(Host)" : "")}");
                pIndex++;
            }

            // Fill up remaining slots with virtual bots in lobby printout (always showing target 4 players)
            for (int k = pIndex; k <= 4; k++)
            {
                sb.AppendLine("<color=#888888>● Bot (Pending Spawn)</color>");
            }

            playerListText.text = sb.ToString();
        }
    }
}
