using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;
using Unity.Services.Core;
using Unity.Services.Authentication;
using Unity.Services.Relay;
using Unity.Services.Relay.Models;
using Unity.Services.Lobbies;
using Unity.Services.Lobbies.Models;
using Unity.Netcode;
using Unity.Netcode.Transports.UTP;

namespace MMystery.Networking
{
    public class NetworkSession : MonoBehaviour
    {
        public static NetworkSession Instance { get; private set; }

        public string JoinCode { get; private set; }
        public bool IsHost { get; private set; }
        public Lobby CurrentLobby { get; private set; }

        private const int MAX_PLAYERS = 6;

        private async void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);

            try
            {
                await UnityServices.InitializeAsync();
                
                if (!AuthenticationService.Instance.IsSignedIn)
                {
                    await AuthenticationService.Instance.SignInAnonymouslyAsync();
                    Debug.Log($"NetworkSession: Signed in anonymously as {AuthenticationService.Instance.PlayerId}");
                }
            }
            catch (Exception e)
            {
                Debug.LogError($"NetworkSession: Service Initialization Failed. Error: {e.Message}");
            }
        }

        public async Task<string> HostGame()
        {
            try
            {
                // 1. Create Relay Allocation
                Allocation allocation = await RelayService.Instance.CreateAllocationAsync(MAX_PLAYERS - 1);
                JoinCode = await RelayService.Instance.GetJoinCodeAsync(allocation.AllocationId);
                IsHost = true;

                Debug.Log($"NetworkSession: Relay Allocation Created. Join Code: {JoinCode}");

                // 2. Configure NGO Transport with Relay
                var transport = NetworkManager.Singleton.GetComponent<UnityTransport>();
                if (transport != null)
                {
                    transport.SetHostRelayData(
                        allocation.RelayServer.IpV4,
                        (ushort)allocation.RelayServer.Port,
                        allocation.AllocationIdBytes,
                        allocation.Key,
                        allocation.ConnectionData
                    );
                }
                else
                {
                    Debug.LogError("NetworkSession: UnityTransport component not found on NetworkManager!");
                }

                // 3. Create Lobby (private), storing Relay Join Code in lobby member data
                CreateLobbyOptions opts = new CreateLobbyOptions
                {
                    IsPrivate = true,
                    Data = new Dictionary<string, DataObject>
                    {
                        { "RelayCode", new DataObject(DataObject.VisibilityOptions.Member, JoinCode) }
                    }
                };

                CurrentLobby = await LobbyService.Instance.CreateLobbyAsync("MMysteryGame", MAX_PLAYERS, opts);
                Debug.Log($"NetworkSession: Lobby Created successfully. LobbyID: {CurrentLobby.Id}");

                // 4. Start NGO as host
                NetworkManager.Singleton.StartHost();

                return JoinCode;
            }
            catch (Exception e)
            {
                Debug.LogError($"NetworkSession: Host Game Failed. Error: {e.Message}");
                throw;
            }
        }

        public async Task JoinGame(string code)
        {
            try
            {
                JoinCode = code.ToUpper().Trim();
                IsHost = false;

                // 1. Join Relay via Join Code
                JoinAllocation joinAlloc = await RelayService.Instance.JoinAllocationAsync(JoinCode);
                Debug.Log($"NetworkSession: Joined Relay Allocation with code {JoinCode}");

                // 2. Configure NGO Transport with Client Relay details
                var transport = NetworkManager.Singleton.GetComponent<UnityTransport>();
                if (transport != null)
                {
                    transport.SetClientRelayData(
                        joinAlloc.RelayServer.IpV4,
                        (ushort)joinAlloc.RelayServer.Port,
                        joinAlloc.AllocationIdBytes,
                        joinAlloc.Key,
                        joinAlloc.ConnectionData,
                        joinAlloc.HostConnectionData
                    );
                }

                // 3. Start NGO as client
                NetworkManager.Singleton.StartClient();
            }
            catch (Exception e)
            {
                Debug.LogError($"NetworkSession: Join Game Failed. Error: {e.Message}");
                throw;
            }
        }

        public void Disconnect()
        {
            try
            {
                if (NetworkManager.Singleton != null)
                {
                    NetworkManager.Singleton.Shutdown();
                }

                if (IsHost && CurrentLobby != null)
                {
                    LobbyService.Instance.DeleteLobbyAsync(CurrentLobby.Id);
                }

                JoinCode = null;
                CurrentLobby = null;
                IsHost = false;
                Debug.Log("NetworkSession: Disconnected and shut down netcode session.");
            }
            catch (Exception e)
            {
                Debug.LogWarning($"NetworkSession: Disconnect error (safe to ignore): {e.Message}");
            }
        }

        // Heartbeat to keep Lobby alive (call every 15 seconds while hosting)
        public async Task SendLobbyHeartbeat(string lobbyId)
        {
            try
            {
                await LobbyService.Instance.SendHeartbeatPingAsync(lobbyId);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"NetworkSession: Lobby Heartbeat failed. Error: {e.Message}");
            }
        }
    }
}
