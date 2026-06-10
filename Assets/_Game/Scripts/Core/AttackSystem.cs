using System.Collections.Generic;
using UnityEngine;
using MMystery.Players;

namespace MMystery.Core
{
    [RequireComponent(typeof(PlayerController))]
    public class AttackSystem : MonoBehaviour
    {
        [SerializeField] private PlayerController owner;
        [SerializeField] private GameObject bulletPrefab;

        private void Awake()
        {
            if (owner == null)
            {
                owner = GetComponent<PlayerController>();
            }
        }

        private void OnEnable()
        {
            if (owner != null)
            {
                owner.OnAttackPressed += HandleAttack;
            }
        }

        private void OnDisable()
        {
            if (owner != null)
            {
                owner.OnAttackPressed -= HandleAttack;
            }
        }

        private void Update()
        {
            if (owner != null && owner.data != null)
            {
                if (owner.data.AttackCooldownFrames > 0)
                {
                    owner.data.AttackCooldownFrames--;
                }
            }
        }

        private void HandleAttack()
        {
            if (owner == null || owner.data == null || !owner.data.IsAlive) return;

            if (owner.data.Role != null)
            {
                if (owner.data.Role.hasKnife)
                {
                    // Gather all players from active game manager or local scene
                    List<PlayerController> allPlayers = FindAllPlayersInScene();
                    TryKnifeAttack(allPlayers);
                }
                else if (owner.data.Role.hasGun)
                {
                    TryGunShoot(bulletPrefab);
                }
            }
        }

        public void TryKnifeAttack(List<PlayerController> allPlayers)
        {
            if (owner == null || owner.data == null || owner.data.Role == null || !owner.data.Role.hasKnife) return;
            if (owner.data.AttackCooldownFrames > 0) return;

            PlayerController nearest = null;
            float nearestDist = GameConstants.KNIFE_RANGE;

            foreach (var player in allPlayers)
            {
                if (player == null || player == owner || player.data == null || !player.data.IsAlive) continue;

                float d = Vector3.Distance(owner.transform.position, player.transform.position);
                if (d < nearestDist)
                {
                    nearestDist = d;
                    nearest = player;
                }
            }

            if (nearest != null)
            {
                // Kill target
                nearest.SetAlive(false);
                owner.data.AttackCooldownFrames = 60; // 1 second cooldown at 60 FPS

                // Trigger kill events
                BulletController.OnKill?.Invoke(nearest.data.DisplayName, "knife");

                // Trigger knife slash sound and visual burst locally if singleplayer
                try
                {
                    var fx = GameObject.FindObjectOfType<MMystery.FX.FXController>();
                    if (fx != null)
                    {
                        fx.PlayDeathBurst(nearest.transform.position);
                        fx.PlaySFX("knife");
                    }
                }
                catch {}
            }
        }

        public void TryGunShoot(GameObject prefabToUse)
        {
            if (owner == null || owner.data == null || owner.data.Role == null || !owner.data.Role.hasGun) return;
            if (prefabToUse == null)
            {
                Debug.LogError("AttackSystem: Firing failed. Bullet prefab is null.");
                return;
            }

            Vector3 dir = owner.transform.forward;
            Vector3 spawnPos = owner.transform.position + Vector3.up * 1.0f + dir * 0.6f;

            GameObject b = Instantiate(prefabToUse, spawnPos, Quaternion.LookRotation(dir));
            BulletController bc = b.GetComponent<BulletController>();
            if (bc != null)
            {
                bc.direction = dir;
                bc.shooterRoleId = owner.data.Role.roleId;
            }

            // Gun is consumed! Replace role with innocent externally or clear gun flag
            owner.data.Role.hasGun = false; // Disable hasGun locally
            
            // Trigger shoot sound locally if singleplayer
            try
            {
                var fx = GameObject.FindObjectOfType<MMystery.FX.FXController>();
                if (fx != null)
                {
                    fx.PlayMuzzleFlash(spawnPos, dir);
                    fx.PlaySFX("gun");
                }
            }
            catch {}
        }

        private List<PlayerController> FindAllPlayersInScene()
        {
            // First look up GameManager for connected players
            List<PlayerController> list = new List<PlayerController>();
            
            try
            {
                var netGM = GameObject.FindObjectOfType<MMystery.Networking.GameManager>();
                if (netGM != null)
                {
                    // Use GameManager players
                    foreach (var p in GameObject.FindObjectsOfType<PlayerController>())
                    {
                        list.Add(p);
                    }
                    return list;
                }
            }
            catch {}

            // Fallback: look up in scene directly
            foreach (var p in GameObject.FindObjectsOfType<PlayerController>())
            {
                list.Add(p);
            }
            return list;
        }
    }
}
