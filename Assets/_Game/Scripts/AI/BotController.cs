using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.AI;
using MMystery.Core;
using MMystery.Players;
using MMystery.Networking;

namespace MMystery.AI
{
    // IMPORTANT: Scene must have a baked NavMesh before bots can navigate.
    // In Unity, use Window -> AI -> Navigation -> Bake in the Manor scene.
    
    [RequireComponent(typeof(NavMeshAgent))]
    public class BotController : MonoBehaviour
    {
        [SerializeField] private BotPersonalitySO personality;
        [SerializeField] private AttackSystem attackSystem;

        public PlayerData data;
        private BotBrain brain;
        private NavMeshAgent agent;
        private List<PlayerController> allPlayerControllers = new List<PlayerController>();

        private float decisionInterval = 0.25f; // recalculate target 4x/sec
        private float decisionTimer = 0f;

        private void Awake()
        {
            brain = new BotBrain { personality = this.personality };
            agent = GetComponent<NavMeshAgent>();
            
            if (attackSystem == null)
            {
                attackSystem = GetComponent<AttackSystem>();
            }

            // Default NavMesh Setup
            agent.speed = GameConstants.WALK_SPEED;
            agent.angularSpeed = 360f;
            agent.acceleration = 12f;
            agent.stoppingDistance = 0.3f;

            // Setup default PlayerData for Bot
            data = new PlayerData
            {
                PlayerId = System.Guid.NewGuid().ToString(),
                DisplayName = "Bot_" + Random.Range(100, 999),
                IsAlive = true,
                IsBot = true,
                Stamina = GameConstants.STAMINA_MAX,
                MBucksThisRound = 0,
                AttackCooldownFrames = 0,
                Position = transform.position,
                FacingDirection = new Vector2(transform.forward.x, transform.forward.z)
            };
        }

        public void InitForRound(PlayerData botData, List<PlayerController> allPlayers)
        {
            data = botData;
            allPlayerControllers = allPlayers;
            
            brain.ResetForRound();
            
            agent.enabled = true;
            agent.Warp(data.Position);
        }

        private void Update()
        {
            if (data == null || !data.IsAlive)
            {
                agent.enabled = false;
                return;
            }

            decisionTimer += Time.deltaTime;
            if (decisionTimer >= decisionInterval)
            {
                decisionTimer = 0f;
                UpdateDecision();
            }

            // Check if should attack
            if (data.Role != null && data.Role.hasKnife)
            {
                if (attackSystem != null && allPlayerControllers != null)
                {
                    attackSystem.TryKnifeAttack(allPlayerControllers);
                }
            }

            // Sync position back to PlayerData
            data.Position = transform.position;
            data.IsMoving = agent.velocity.magnitude > 0.1f;
            if (data.IsMoving)
            {
                data.AnimPhase += Time.deltaTime * agent.velocity.magnitude;
            }
            data.FacingDirection = new Vector2(transform.forward.x, transform.forward.z);
        }

        private void UpdateDecision()
        {
            if (allPlayerControllers == null) return;

            List<PlayerData> allData = allPlayerControllers.Select(pc => pc.data).ToList();
            
            Vector3 droppedGunPos = Vector3.negativeInfinity;
            List<Vector3> buckPositions = new List<Vector3>();

            if (GameManager.Instance != null)
            {
                droppedGunPos = GameManager.Instance.DroppedGunPosition;
                buckPositions = GameManager.Instance.BuckPositions;
            }

            // Adjust bot speed depending on role
            agent.speed = (data.Role != null && data.Role.roleId == "murderer")
                ? GameConstants.SPRINT_SPEED * 0.85f
                : GameConstants.WALK_SPEED;

            Vector3 target = brain.ChooseTarget(data, allData, droppedGunPos, buckPositions);
            
            if (agent.isActiveAndEnabled)
            {
                if (Vector3.Distance(target, transform.position) > 0.5f)
                {
                    agent.SetDestination(target);
                }
            }
        }
    }
}
