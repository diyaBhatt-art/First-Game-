using UnityEngine;
using MMystery.Players;

namespace MMystery.Core
{
    public class BuckPickup : MonoBehaviour
    {
        [SerializeField] private int value = 0;

        private void Start()
        {
            if (value == 0)
            {
                value = Random.Range(1, 4); // Grants 1, 2, or 3 bucks randomly
            }
        }

        private void OnTriggerEnter(Collider other)
        {
            // Try to find local PlayerController
            PlayerController pc = other.GetComponent<PlayerController>();
            if (pc != null && pc.data != null)
            {
                // In Netcode multiplayer sessions, trigger collection calculations ONLY on the server
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
                    // Ignore client trigger checks, wait for server to destroy the object and sync
                    return;
                }

                PlayerData data = pc.data;
                if (data.IsAlive && data.MBucksThisRound < GameConstants.MAX_BUCKS_PER_ROUND)
                {
                    int maxAllowed = GameConstants.MAX_BUCKS_PER_ROUND - data.MBucksThisRound;
                    int collected = Mathf.Min(value, maxAllowed);

                    data.MBucksThisRound += collected;

                    // Trigger the collected event on BuckSpawner
                    var spawner = GetComponentInParent<BuckSpawner>();
                    if (spawner != null)
                    {
                        spawner.TriggerBuckCollected(transform.position, collected);
                    }

                    // Play collection sound & VFX locally if singleplayer (in netcode this is synced by GameManager/FXController)
                    if (!isNetActive)
                    {
                        try
                        {
                            var fx = GameObject.FindObjectOfType<MMystery.FX.FXController>();
                            if (fx != null)
                            {
                                fx.PlayCoinCollect(transform.position);
                            }
                        }
                        catch {}
                    }

                    Destroy(gameObject);
                }
            }
        }
    }
}
