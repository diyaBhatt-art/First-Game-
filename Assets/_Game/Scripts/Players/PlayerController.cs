using UnityEngine;
using UnityEngine.InputSystem;
using MMystery.Core;

namespace MMystery.Players
{
    [RequireComponent(typeof(CharacterController))]
    public class PlayerController : MonoBehaviour
    {
        [SerializeField] private float rotationSmoothSpeed = 15f;
        [SerializeField] private Transform cameraTransform;

        private CharacterController _characterController;
        private Vector2 _moveInput;
        private bool _isSprinting;
        private bool _isAttacking;

        public PlayerData data { get; private set; }
        public bool IsSprinting => _isSprinting;

        public event System.Action OnAttackPressed;

        private void Awake()
        {
            _characterController = GetComponent<CharacterController>();
            
            // Initialize PlayerData with default values
            data = new PlayerData
            {
                PlayerId = System.Guid.NewGuid().ToString(),
                DisplayName = "Player_" + Random.Range(100, 999),
                IsAlive = true,
                IsBot = false,
                Stamina = GameConstants.STAMINA_MAX,
                MBucksThisRound = 0,
                AttackCooldownFrames = 0,
                Position = transform.position,
                FacingDirection = new Vector2(transform.forward.x, transform.forward.z)
            };
        }

        private void Start()
        {
            if (cameraTransform == null && Camera.main != null)
            {
                cameraTransform = Camera.main.transform;
            }
        }

        // Input System Message Handlers (Send Messages mode)
        public void OnMove(InputValue value)
        {
            _moveInput = value.Get<Vector2>();
        }

        public void OnSprint(InputValue value)
        {
            _isSprinting = value.isPressed;
        }

        public void OnAttack(InputValue value)
        {
            if (value.isPressed)
            {
                _isAttacking = true;
                OnAttackPressed?.Invoke();
            }
            else
            {
                _isAttacking = false;
            }
        }

        public void ResetAttackTrigger()
        {
            _isAttacking = false;
        }

        private void Update()
        {
            if (!data.IsAlive) return;

            // Check if we are running in multiplayer network mode (handled by NetworkPlayer)
            // If Netcode is active and we are NOT the server/host, we don't apply local physics directly
            bool isNetActive = false;
            try
            {
                var netMgr = Unity.Netcode.NetworkManager.Singleton;
                if (netMgr != null && netMgr.IsListening)
                {
                    isNetActive = true;
                }
            }
            catch {}

            if (!isNetActive)
            {
                // Local singleplayer/editor-test movement direct tick
                ApplyMovementTick(_moveInput, _isSprinting, Time.deltaTime);
            }
        }

        // Apply Server Input (called by ServerRpc in NetworkPlayer)
        public void ApplyServerInput(Vector2 moveInput, bool sprinting, bool attacking)
        {
            ApplyMovementTick(moveInput, sprinting, Time.deltaTime);
            if (attacking)
            {
                OnAttackPressed?.Invoke();
            }
        }

        private void ApplyMovementTick(Vector2 moveInput, bool sprinting, float dt)
        {
            if (!data.IsAlive) return;

            // 1. Compute camera relative movement direction
            float cameraYaw = 0f;
            if (cameraTransform != null)
            {
                // Try to read ThirdPersonCamera component first
                var tpc = cameraTransform.GetComponent<ThirdPersonCamera>();
                cameraYaw = (tpc != null) ? tpc.Yaw : cameraTransform.eulerAngles.y;
            }
            Vector3 moveDir = CameraRelativeMovement.GetCameraRelativeDirection(moveInput, cameraYaw);

            // 2. Determine speed based on stamina
            float speed = GameConstants.WALK_SPEED;
            if (sprinting && moveInput.magnitude > 0.1f && data.Stamina > 0f)
            {
                speed = GameConstants.SPRINT_SPEED;
                // Drain stamina
                data.Stamina = Mathf.Max(0f, data.Stamina - GameConstants.STAMINA_DRAIN * dt);
            }
            else
            {
                // Regen stamina
                data.Stamina = Mathf.Min(GameConstants.STAMINA_MAX, data.Stamina + GameConstants.STAMINA_REGEN * dt);
            }

            // 3. Move via CharacterController
            Vector3 velocity = moveDir * speed;
            
            // Apply gravity
            if (!_characterController.isGrounded)
            {
                velocity.y = -9.8f;
            }
            else
            {
                velocity.y = -0.5f; // small down force to stick to ground
            }

            _characterController.Move(velocity * dt);

            // 4. Smooth rotation
            if (moveDir.magnitude > 0.1f)
            {
                Quaternion targetRot = Quaternion.LookRotation(moveDir);
                // Keep upright
                targetRot.x = 0;
                targetRot.z = 0;
                transform.rotation = Quaternion.Slerp(transform.rotation, targetRot, rotationSmoothSpeed * dt);
            }

            // 5. Update data state
            data.IsMoving = moveDir.magnitude > 0.1f;
            if (data.IsMoving)
            {
                data.AnimPhase += dt * speed;
            }
            data.Position = transform.position;
            data.FacingDirection = new Vector2(transform.forward.x, transform.forward.z);
        }

        public void SetAlive(bool alive)
        {
            data.IsAlive = alive;
            _characterController.enabled = alive;
        }

        public void Teleport(Vector3 pos)
        {
            _characterController.enabled = false;
            transform.position = pos;
            data.Position = pos;
            _characterController.enabled = true;
        }

        public void ResetForRound(Vector3 spawnPos, RoleDefinitionSO role)
        {
            data.Role = role;
            data.IsAlive = true;
            data.Stamina = GameConstants.STAMINA_MAX;
            data.MBucksThisRound = 0;
            data.AttackCooldownFrames = 0;
            _characterController.enabled = true;
            Teleport(spawnPos);
        }
    }
}
