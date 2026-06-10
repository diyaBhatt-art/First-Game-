using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Unity.Netcode;
using MMystery.Core;
using MMystery.Players;
using MMystery.AI;

namespace MMystery.Networking
{
    public class GameManager : NetworkBehaviour
    {
        public static GameManager Instance { get; private set; }

        [SerializeField] private RoleDefinitionSO[] allRoles;
        [SerializeField] private MapDefinitionSO currentMap;
        [SerializeField] private GameObject botPrefab;
        [SerializeField] private RoundManager roundManager;
        [SerializeField] private BuckSpawner buckSpawner;

        private List<NetworkPlayer> connectedPlayers = new List<NetworkPlayer>();
        private List<BotController> bots = new List<BotController>();

        private Vector3 droppedGunPosition = Vector3.negativeInfinity;
        public Vector3 DroppedGunPosition => droppedGunPosition;
        public List<Vector3> BuckPositions => buckSpawner?.GetBuckPositions();

        // URP/Canvas UI Events
        public static event Action<string, string, string> OnKillConfirmed; // killerName, victimName, weapon
        public static event Action<string> OnRoundEnded; // "murderer" or "innocents"

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);

            if (roundManager == null) roundManager = GetComponentInChildren<RoundManager>();
            if (buckSpawner == null) buckSpawner = GetComponentInChildren<BuckSpawner>();
        }

        public override void OnNetworkSpawn()
        {
            if (IsServer)
            {
                NetworkManager.Singleton.OnClientConnectedCallback += OnClientConnected;
                NetworkManager.Singleton.OnClientDisconnectCallback += OnClientDisconnected;
                
                // Track already connected host
                var hostPlayer = NetworkManager.Singleton.LocalClient.PlayerObject?.GetComponent<NetworkPlayer>();
                if (hostPlayer != null)
                {
                    connectedPlayers.Add(hostPlayer);
                }

                // Subscribe to bullet deaths
                BulletController.OnKill += HandleKillReceived;
            }
        }

        public override void OnNetworkDespawn()
        {
            if (IsServer && NetworkManager.Singleton != null)
            {
                NetworkManager.Singleton.OnClientConnectedCallback -= OnClientConnected;
                NetworkManager.Singleton.OnClientDisconnectCallback -= OnClientDisconnected;
                BulletController.OnKill -= HandleKillReceived;
            }
        }

        private void OnClientConnected(ulong clientId)
        {
            var pObj = NetworkManager.Singleton.ConnectedClients[clientId].PlayerObject;
            if (pObj != null)
            {
                var netPlayer = pObj.GetComponent<NetworkPlayer>();
                if (netPlayer != null && !connectedPlayers.Contains(netPlayer))
                {
                    connectedPlayers.Add(netPlayer);
                    Debug.Log($"GameManager: Human player connected. Total humans: {connectedPlayers.Count}");
                }
            }
        }

        private void OnClientDisconnected(ulong clientId)
        {
            connectedPlayers.RemoveAll(p => p == null || p.OwnerClientId == clientId);
            Debug.Log($"GameManager: Human player disconnected. Total humans: {connectedPlayers.Count}");
        }

        public RoleDefinitionSO GetRoleById(string roleId)
        {
            return allRoles.FirstOrDefault(r => r.roleId == roleId);
        }

        [ServerRpc(RequireOwnership = false)]
        public void BeginRoundServerRpc()
        {
            BeginRound();
        }

        public void BeginRound()
        {
            if (!IsServer) return;

            Debug.Log("GameManager: Starting authoritative round setup.");

            // Clear old game elements
            droppedGunPosition = Vector3.negativeInfinity;
            foreach (var b in bots)
            {
                if (b != null)
                {
                    b.GetComponent<NetworkObject>().Despawn();
                }
            }
            bots.Clear();

            // Refresh human players list in case spawned late
            connectedPlayers = GameObject.FindObjectsOfType<NetworkPlayer>().ToList();

            if (currentMap == null)
            {
                Debug.LogError("GameManager: CurrentMap MapDefinitionSO is not assigned!");
                return;
            }

            Vector3[] spawns = currentMap.spawnPoints;
            if (spawns == null || spawns.Length == 0)
            {
                Debug.LogError("GameManager: MapDefinition spawnPoints is empty!");
                return;
            }

            // Assign Spawn Points to humans
            int i = 0;
            foreach (var player in connectedPlayers)
            {
                var pc = player.GetComponent<PlayerController>();
                Vector3 spawnPos = spawns[i % spawns.Length];
                pc.Teleport(spawnPos);
                i++;
            }

            // Fill remaining slots with bots up to exactly 4 players
            int botsNeeded = 4 - connectedPlayers.Count;
            if (botsNeeded > 0 && botPrefab != null)
            {
                for (int j = 0; j < botsNeeded; j++)
                {
                    Vector3 spawnPos = spawns[i % spawns.Length];
                    GameObject botObj = Instantiate(botPrefab, spawnPos, Quaternion.identity);
                    
                    var netObj = botObj.GetComponent<NetworkObject>();
                    netObj.Spawn(true); // Authoritative server spawn

                    var botCtrl = botObj.GetComponent<BotController>();
                    bots.Add(botCtrl);
                    i++;
                }
            }

            // Shuffle and Assign Roles
            List<PlayerData> allData = connectedPlayers
                .Select(p => p.GetComponent<PlayerController>().data)
                .Concat(bots.Select(b => b.data)).ToList();
            
            RoleAssigner.AssignRoles(allData, allRoles.ToList());

            // Synchronize roles privately to each human player
            foreach (var player in connectedPlayers)
            {
                PlayerData pd = player.GetComponent<PlayerController>().data;
                ClientRpcParams targetParams = new ClientRpcParams
                {
                    Send = new ClientRpcSendParams
                    {
                        TargetClientIds = new[] { player.OwnerClientId }
                    }
                };
                player.AssignRoleClientRpc(pd.Role.roleId, targetParams);
            }

            // Bind bots to round target references
            List<PlayerController> allPCs = connectedPlayers
                .Select(p => p.GetComponent<PlayerController>())
                .Concat(bots.Select(b => b.GetComponent<PlayerController>()))
                .ToList();

            foreach (var bot in bots)
            {
                bot.InitForRound(bot.data, allPCs);
            }

            // Spawn bucks (coins)
            if (buckSpawner != null)
            {
                buckSpawner.SpawnBucks(currentMap.buckSpawnZones);
            }

            // Start round countdown and link win evaluations
            if (roundManager != null)
            {
                roundManager.SetPlayersList(allData);
                roundManager.StartRound();
                roundManager.OnRoundEnd += EndRound;
            }
        }

        private void Update()
        {
            if (!IsServer) return;

            // Authoritative server-side gun drop monitoring
            if (droppedGunPosition == Vector3.negativeInfinity)
            {
                // Watch if the Sheriff has died
                List<PlayerController> allPCs = connectedPlayers
                    .Select(p => p.GetComponent<PlayerController>())
                    .Concat(bots.Select(b => b.GetComponent<PlayerController>()))
                    .ToList();

                foreach (var pc in allPCs)
                {
                    if (pc.data.Role != null && pc.data.Role.roleId == "sheriff" && !pc.data.IsAlive)
                    {
                        droppedGunPosition = pc.transform.position;
                        Debug.Log($"GameManager: Sheriff has died! Dropped gun at {droppedGunPosition}");
                        break;
                    }
                }
            }
            else
            {
                // Watch if any Innocent collects the dropped gun
                List<PlayerController> allPCs = connectedPlayers
                    .Select(p => p.GetComponent<PlayerController>())
                    .Concat(bots.Select(b => b.GetComponent<PlayerController>()))
                    .ToList();

                foreach (var pc in allPCs)
                {
                    if (pc.data.IsAlive && pc.data.Role != null && pc.data.Role.roleId == "innocent")
                    {
                        float dist = Vector3.Distance(pc.transform.position, droppedGunPosition);
                        if (dist < 1.5f) // Collection range (1.5 world units)
                        {
                            pc.data.Role.hasGun = true;
                            pc.data.Role.roleId = "sheriff"; // promote their gun flag
                            droppedGunPosition = Vector3.negativeInfinity;
                            Debug.Log($"GameManager: Innocent {pc.data.DisplayName} picked up the dropped Sheriff's gun!");
                            break;
                        }
                    }
                }
            }
        }

        private void HandleKillReceived(string victim, string weapon)
        {
            if (!IsServer) return;

            string killerName = GetKillerName(weapon);
            KillConfirmedClientRpc(killerName, victim, weapon);
        }

        private string GetKillerName(string weapon)
        {
            List<PlayerData> allPlayers = connectedPlayers
                .Select(p => p.GetComponent<PlayerController>().data)
                .Concat(bots.Select(b => b.data)).ToList();

            if (weapon == "knife")
            {
                // Killer is the Murderer
                var murderer = allPlayers.FirstOrDefault(p => p.Role != null && p.Role.roleId == "murderer");
                return murderer != null ? murderer.DisplayName : "Murderer";
            }
            else if (weapon == "gun")
            {
                // Killer is the Sheriff (or innocent who collected the gun)
                var shooter = allPlayers.FirstOrDefault(p => p.IsAlive && p.Role != null && p.Role.roleId == "sheriff");
                return shooter != null ? shooter.DisplayName : "Sheriff";
            }

            return "Unknown";
        }

        private void EndRound(string winner)
        {
            if (!IsServer) return;

            roundManager.OnRoundEnd -= EndRound;
            EndRoundClientRpc(winner);
        }

        [ClientRpc]
        private void EndRoundClientRpc(string winner)
        {
            OnRoundEnded?.Invoke(winner);
        }

        [ClientRpc]
        private void KillConfirmedClientRpc(string killer, string victim, string weapon)
        {
            OnKillConfirmed?.Invoke(killer, victim, weapon);
        }
    }
}
