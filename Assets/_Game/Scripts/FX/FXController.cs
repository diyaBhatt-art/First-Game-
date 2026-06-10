using UnityEngine;
using UnityEngine.VFX;

namespace MMystery.FX
{
    public class FXController : MonoBehaviour
    {
        public static FXController Instance { get; private set; }

        [Header("VFX Prefabs (VFX Graph assets)")]
        [SerializeField] private VisualEffect deathBurstPrefab;
        [SerializeField] private VisualEffect coinCollectPrefab;
        [SerializeField] private VisualEffect muzzleFlashPrefab;
        [SerializeField] private VisualEffect bulletImpactPrefab;

        [Header("Audio Sources")]
        [SerializeField] private AudioSource sfxSource;
        [SerializeField] private AudioSource musicSource;

        [Header("Audio Clips (SFX)")]
        [SerializeField] private AudioClip knifeSlashSFX;
        [SerializeField] private AudioClip gunShootSFX;
        [SerializeField] private AudioClip bulletHitSFX;
        [SerializeField] private AudioClip coinCollectSFX;
        [SerializeField] private AudioClip deathSFX;

        [Header("Audio Clips (Ambient/Music)")]
        [SerializeField] private AudioClip lobbyMusic;
        [SerializeField] private AudioClip roundMusic;

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);

            // Dynamically add audio sources if not assigned in Inspector
            if (sfxSource == null)
            {
                sfxSource = gameObject.AddComponent<AudioSource>();
                sfxSource.spatialBlend = 0.5f; // partial 3D sound
            }

            if (musicSource == null)
            {
                musicSource = gameObject.AddComponent<AudioSource>();
                musicSource.loop = true;
                musicSource.spatialBlend = 0f; // 2D flat sound
                musicSource.volume = 0.5f;
            }
        }

        private void Start()
        {
            // Play lobby theme on launch
            PlayMusic("lobby");
        }

        // VFX Spawning Helpers
        public void PlayDeathBurst(Vector3 position)
        {
            if (deathBurstPrefab != null)
            {
                VisualEffect vfx = Instantiate(deathBurstPrefab, position, Quaternion.identity);
                vfx.Play();
                Destroy(vfx.gameObject, 2f); // Clean up after 2s
            }
        }

        public void PlayCoinCollect(Vector3 position)
        {
            if (coinCollectPrefab != null)
            {
                VisualEffect vfx = Instantiate(coinCollectPrefab, position, Quaternion.identity);
                vfx.Play();
                Destroy(vfx.gameObject, 1.5f); // Clean up
            }
        }

        public void PlayMuzzleFlash(Vector3 position, Vector3 direction)
        {
            if (muzzleFlashPrefab != null)
            {
                VisualEffect vfx = Instantiate(muzzleFlashPrefab, position, Quaternion.LookRotation(direction));
                vfx.Play();
                Destroy(vfx.gameObject, 0.5f);
            }
        }

        public void PlayBulletImpact(Vector3 position, Vector3 normal)
        {
            if (bulletImpactPrefab != null)
            {
                VisualEffect vfx = Instantiate(bulletImpactPrefab, position, Quaternion.LookRotation(normal));
                vfx.Play();
                Destroy(vfx.gameObject, 1f);
            }
        }

        // SFX Trigger Helpers
        public void PlaySFX(string sfxName, Vector3 position = default)
        {
            AudioClip clip = null;

            switch (sfxName.ToLower())
            {
                case "knife":
                    clip = knifeSlashSFX;
                    break;
                case "gun":
                    clip = gunShootSFX;
                    break;
                case "hit":
                    clip = bulletHitSFX;
                    break;
                case "coin":
                    clip = coinCollectSFX;
                    break;
                case "death":
                    clip = deathSFX;
                    break;
            }

            if (clip != null)
            {
                if (position != default)
                {
                    // Play at specific 3D spatial location
                    AudioSource.PlayClipAtPoint(clip, position);
                }
                else
                {
                    // Play general flat sound
                    sfxSource.PlayOneShot(clip);
                }
            }
        }

        // Ambient Music Helpers
        public void PlayMusic(string musicName)
        {
            AudioClip clip = null;

            if (musicName.ToLower() == "lobby")
            {
                clip = lobbyMusic;
            }
            else if (musicName.ToLower() == "game")
            {
                clip = roundMusic;
            }

            if (clip != null && musicSource.clip != clip)
            {
                musicSource.Stop();
                musicSource.clip = clip;
                musicSource.Play();
            }
        }
    }
}
