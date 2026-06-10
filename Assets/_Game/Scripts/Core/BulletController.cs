using System;
using UnityEngine;
using MMystery.Players;

namespace MMystery.Core
{
    public class BulletController : MonoBehaviour
    {
        public Vector3 direction;
        public string shooterRoleId;
        public bool isActive = true;
        public float lifespan = 3f;

        // Static Events (to be observed by GameManager, FXController, or HUD)
        public static event Action<Vector3> OnBulletHitWall;
        public static event Action<string, string> OnKill; // victimName, weapon

        private void Update()
        {
            if (!isActive) return;

            lifespan -= Time.deltaTime;
            if (lifespan <= 0f)
            {
                Destroy(gameObject);
                return;
            }

            transform.position += direction * GameConstants.BULLET_SPEED * Time.deltaTime;
        }

        private void OnTriggerEnter(Collider other)
        {
            if (!isActive) return;

            // Check if it hit a wall
            if (other.CompareTag("Wall"))
            {
                isActive = false;
                OnBulletHitWall?.Invoke(transform.position);
                
                // Play impact effect locally if singleplayer (netcode does this via event broadcast)
                try
                {
                    var fx = GameObject.FindObjectOfType<MMystery.FX.FXController>();
                    if (fx != null)
                    {
                        fx.PlayBulletImpact(transform.position, -direction.normalized);
                    }
                }
                catch {}

                Destroy(gameObject);
                return;
            }

            // Check if it hit a player
            PlayerController pc = other.GetComponent<PlayerController>();
            if (pc != null && pc.data != null && pc.data.IsAlive)
            {
                // In Netcode multiplayer sessions, trigger hit calculations ONLY on the server
                bool isNetActive = false;
                bool isServer = false;
                try
                {
                    var netMgr = Unity.Netcode.NetworkManager.Singleton;
                    if (netMgr != null && netMgr.IsListening)
                    {
                        isNetActive = true;
                        isServer = netMgr.IsServer;
                    }
                }
                catch {}

                if (isNetActive && !isServer)
                {
                    // Client does not determine kills, wait for server
                    return;
                }

                // Gun shots ONLY damage the Murderer!
                if (pc.data.Role != null && pc.data.Role.roleId == "murderer")
                {
                    pc.SetAlive(false);
                    OnKill?.Invoke(pc.data.DisplayName, "gun");
                    isActive = false;
                    
                    // Sync VFX
                    if (!isNetActive)
                    {
                        try
                        {
                            var fx = GameObject.FindObjectOfType<MMystery.FX.FXController>();
                            if (fx != null)
                            {
                                fx.PlayDeathBurst(pc.transform.position);
                            }
                        }
                        catch {}
                    }

                    Destroy(gameObject);
                }
                else
                {
                    // Bullets pass through innocents or the sheriff harmlessly, or just get absorbed without damaging them
                    isActive = false;
                    Destroy(gameObject);
                }
            }
        }
    }
}
