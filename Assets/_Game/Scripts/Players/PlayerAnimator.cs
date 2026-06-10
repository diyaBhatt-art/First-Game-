using UnityEngine;

namespace MMystery.Players
{
    [RequireComponent(typeof(Animator))]
    public class PlayerAnimator : MonoBehaviour
    {
        private Animator _animator;
        private PlayerController _controller;

        private void Awake()
        {
            _animator = GetComponent<Animator>();
            _controller = GetComponent<PlayerController>();
        }

        private void Update()
        {
            if (_controller == null || _controller.data == null) return;

            float speedVal = 0f;
            if (_controller.data.IsMoving)
            {
                speedVal = _controller.IsSprinting ? 1.0f : 0.5f;
            }

            _animator.SetFloat("Speed", speedVal);
            _animator.SetBool("IsAlive", _controller.data.IsAlive);
        }
    }
}
