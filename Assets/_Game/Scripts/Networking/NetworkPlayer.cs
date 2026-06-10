using UnityEngine;
using Unity.Netcode;
using MMystery.Players;
using MMystery.Core;
using MMystery.UI;

namespace MMystery.Networking
{
    [RequireComponent(typeof(PlayerController))]
    public class NetworkPlayer : NetworkBehaviour
    {
        // Server-Authoritative Sync Variables
        public readonly NetworkVariable<bool> IsAlive = new NetworkVariable<bool>(
            true, NetworkVariableWritePermission.Server, NetworkVariableReadPermission.Everyone);
        
        public readonly NetworkVariable<Vector3> Position = new NetworkVariable<Vector3>(
            Vector3.zero, NetworkVariableWritePermission.Server, NetworkVariableReadPermission.Everyone);
        
        public readonly NetworkVariable<Vector2> FacingDirection = new NetworkVariable<Vector2>(
            Vector2.zero, NetworkVariableWritePermission.Server, NetworkVariableReadPermission.Everyone);
        
        public readonly NetworkVariable<bool> IsMoving = new NetworkVariable<bool>(
            false, NetworkVariableWritePermission.Server, NetworkVariableReadPermission.Everyone);
        
        public readonly NetworkVariable<int> MBucksThisRound = new NetworkVariable<int>(
            0, NetworkVariableWritePermission.Server, NetworkVariableReadPermission.Everyone);

        private PlayerController _playerController;

        private void Awake()
        {
            _playerController = GetComponent<PlayerController>();
        }

        public override void OnNetworkSpawn()
        {
            if (IsOwner)
            {
                // Enable inputs and scripts locally
                _playerController.enabled = true;
                
                var tpc = Camera.main?.GetComponent<ThirdPersonCamera>();
                if (tpc != null)
                {
                    tpc.LockCursor(true);
                }
            }
            else
            {
                // Disable controls on remote clones (server updates positions)
                _playerController.enabled = false;
            }

            // Sync initial state
            OnVariableChanged(false, IsAlive.Value);
            MBucksThisRound.OnValueChanged += OnBucksChanged;
            IsAlive.OnValueChanged += OnVariableChanged;
        }

        public override void OnNetworkDespawn()
        {
            MBucksThisRound.OnValueChanged -= OnBucksChanged;
            IsAlive.OnValueChanged -= OnVariableChanged;
        }

        private void OnBucksChanged(int oldVal, int newVal)
        {
            if (_playerController != null && _playerController.data != null)
            {
                _playerController.data.MBucksThisRound = newVal;
            }
        }

        private void OnVariableChanged(bool oldVal, bool newVal)
        {
            if (_playerController != null)
            {
                _playerController.SetAlive(newVal);
            }
        }

        private void Update()
        {
            if (IsOwner)
            {
                // 1. Read input from local player actions
                Vector2 moveInput = Vector2.zero;
                bool sprinting = false;
                bool attacking = false;

                // Safely read from Unity Input Action
                var playerInput = GetComponent<UnityEngine.InputSystem.PlayerInput>();
                if (playerInput != null)
                {
                    var moveAct = playerInput.actions["Move"];
                    var sprintAct = playerInput.actions["Sprint"];
                    var attackAct = playerInput.actions["Attack"];

                    if (moveAct != null) moveInput = moveAct.ReadValue<Vector2>();
                    if (sprintAct != null) sprinting = sprintAct.IsPressed();
                    if (attackAct != null) attacking = attackAct.WasPressedThisFrame();
                }

                // 2. Submit to Server authoritative tick
                SubmitInputServerRpc(moveInput, sprinting, attacking);
            }
            else if (!IsServer)
            {
                // Clients lerp remote clone positions to match synchronized Server values
                transform.position = Vector3.Lerp(transform.position, Position.Value, Time.deltaTime * 15f);
                if (FacingDirection.Value.magnitude > 0.01f)
                {
                    Vector3 lookTarget = new Vector3(FacingDirection.Value.x, 0f, FacingDirection.Value.y);
                    transform.rotation = Quaternion.Slerp(transform.rotation, Quaternion.LookRotation(lookTarget), Time.deltaTime * 15f);
                }

                // Sync data states for animations on other machines
                if (_playerController != null && _playerController.data != null)
                {
                    _playerController.data.IsMoving = IsMoving.Value;
                    _playerController.data.Position = transform.position;
                    _playerController.data.FacingDirection = FacingDirection.Value;
                    if (IsMoving.Value)
                    {
                        _playerController.data.AnimPhase += Time.deltaTime * GameConstants.WALK_SPEED;
                    }
                }
            }
        }

        private void LateUpdate()
        {
            if (IsServer)
            {
                // Host/Server writes authoritative PlayerController data to NetworkVariables
                if (_playerController != null && _playerController.data != null)
                {
                    IsAlive.Value = _playerController.data.IsAlive;
                    Position.Value = transform.position;
                    FacingDirection.Value = _playerController.data.FacingDirection;
                    IsMoving.Value = _playerController.data.IsMoving;
                    MBucksThisRound.Value = _playerController.data.MBucksThisRound;
                }
            }
        }

        [ServerRpc]
        private void SubmitInputServerRpc(Vector2 moveInput, bool sprinting, bool attacking)
        {
            if (!IsAlive.Value) return;

            // Apply movement mechanics to server's duplicate
            if (_playerController != null)
            {
                _playerController.ApplyServerInput(moveInput, sprinting, attacking);
                _playerController.ResetAttackTrigger();
            }
        }

        [ClientRpc]
        public void AssignRoleClientRpc(string roleId, ClientRpcParams rpcParams = default)
        {
            Debug.Log($"NetworkPlayer: Assigning role {roleId} on client.");
            
            // Client looks up RoleDefinitionSO by roleId from GameManager cached list
            RoleDefinitionSO targetRole = null;
            if (GameManager.Instance != null)
            {
                targetRole = GameManager.Instance.GetRoleById(roleId);
            }

            if (targetRole != null && _playerController != null && _playerController.data != null)
            {
                _playerController.data.Role = targetRole;

                // Sync weapons capability
                _playerController.data.Role.hasKnife = targetRole.hasKnife;
                _playerController.data.Role.hasGun = targetRole.hasGun;
                
                // Show role reveal UI locally
                var reveal = GameObject.FindObjectOfType<RoleRevealScreen>();
                if (reveal != null)
                {
                    reveal.ShowReveal(targetRole);
                }
            }
            else
            {
                Debug.LogError($"NetworkPlayer: Failed to lookup role '{roleId}' from client list.");
            }
        }
    }
}
