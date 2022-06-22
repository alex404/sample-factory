import multiprocessing
import os
from argparse import ArgumentParser
from os.path import join

from sample_factory.utils.utils import str2bool


def add_basic_cli_args(p: ArgumentParser):
    p.add_argument('-h', '--help', action='store_true', help='Print the help message', required=False)
    p.add_argument('--algo', type=str, default='APPO', help='Algorithm to use')
    p.add_argument('--env', type=str, default=None, required=True, help='Name of the environment to use')
    p.add_argument(
        '--experiment', type=str, default='default_experiment',
        help='Unique experiment name. This will also be the name for the experiment folder in the train dir.'
             'If the experiment folder with this name aleady exists the experiment will be RESUMED!'
             'Any parameters passed from command line that do not match the parameters stored in the experiment cfg.json file will be overridden.',
    )
    p.add_argument('--train_dir', default=join(os.getcwd(), 'train_dir'), type=str, help='Root for all experiments')
    p.add_argument(
        '--experiments_root', type=str, default=None, required=False,
        help='If not None, store experiment data in the specified subfolder of train_dir. Useful for groups of experiments (e.g. gridsearch)',
    )  # TODO: do we absolutely need this?

    p.add_argument('--device', default='gpu', type=str, choices=['gpu', 'cpu'], help='CPU training is only recommended for smaller e.g. MLP policies')
    p.add_argument('--seed', default=None, type=int, help='Set a fixed seed value')


def add_rl_args(p: ArgumentParser):
    """Arguments not specific to any particular RL algorithm."""
    # RL training system configuration (i.e. whether sync or async, etc.)
    p.add_argument('--num_policies', default=1, type=int, help='Number of policies to train jointly, i.e. for multi-agent environments')
    p.add_argument(
        '--async_rl', default=True, type=str2bool,
        help='Collect experience asynchronously while learning on the previous batch. '
             'This is semantically different from standard synchronous actor-critic (or PPO) because '
             'not all of the experience will be collected by the latest policy thus increasing policy lag. '
             'Negative effects of using async_rl can range from negligible (just grants you throughput boost) '
             'to quite serious where you can consider switching it off. It all depends how sensitive your experiment is to policy lag. '
             'Envs with complex action spaces and RNN policies tend to be particularly sensitive. ',
    )
    p.add_argument('--serial_mode', default=False, type=str2bool, help='Enable serial mode: run everything completely synchronously in the same process')
    p.add_argument(
        '--batched_sampling', default=True, type=str2bool,
        help='Batched sampling allows the data to be processed in big batches on the rollout worker.'
             'This is especially important for GPU-accelerated vectorized environments such as Megaverse or IsaacGym. '
             'As a downside, in batched mode we do not support (for now) some of the features, such as population-based self-play '
             'or inactive agents. Each sampler (rollout worker) process only collects data for a single policy.',
    )
    p.add_argument(
        '--num_batches_to_accumulate', default=2, type=int,
        help='This parameter governs the maximum number of training batches the learner can accumulate before further experience collection is stopped.'
             'The default value will set this to 2, so if the experience collection is faster than the training, '
             'the learner will accumulate enough minibatches for 2 iterations of training (but no more). This is a good balance between policy-lag and throughput.'
             'When the limit is reached, the learner will notify the actor workers that they ought to stop the experience collection until accumulated minibatches '
             'are processed. Set this parameter to 1 to further reduce policy-lag. '
             'If the experience collection is very non-uniform, increasing this parameter can increase overall throughput, at the cost of increased policy-lag.'
    )
    p.add_argument(
        '--worker_num_splits', default=2, type=int,
        help='Typically we split a vector of envs into two parts for "double buffered" experience collection '
             'Set this to 1 to disable double buffering. Set this to 3 for triple buffering!',
    )
    p.add_argument('--policy_workers_per_policy', default=1, type=int, help='Number of policy workers that compute forward pass (per policy)')
    p.add_argument(
        '--max_policy_lag', default=10000, type=int,
        help='Max policy lag in policy versions. Discard all experience that is older than this. This should be increased for configurations with multiple epochs of SGD because naturally policy-lag may exceed this value.',
    )

    # RL algorithm data collection & learning regime (rollout length, batch size, etc.)
    p.add_argument(
        '--num_workers', default=multiprocessing.cpu_count(), type=int,
        help='Number of parallel environment workers. Should be less than num_envs and should divide num_envs.'
             'Use this in async mode.'
    )
    p.add_argument(
        '--num_envs_per_worker', default=2, type=int,
        help='Number of envs on a single CPU actor, in high-throughput configurations this should be in 10-30 range for Atari/VizDoom'
             'Must be even for double-buffered sampling!',
    )
    p.add_argument('--batch_size', default=1024, type=int, help='Minibatch size for SGD')
    p.add_argument(
        '--num_batches_per_epoch', default=1, type=int,
        help='This determines the training dataset size for each iteration of training. We collect this many minibatches before performing any SGD. '
             'Example: if batch_size=128 and num_batches_per_epoch=2, then learner will process 2*128=256 environment transitions in one training iteration.'
    )
    p.add_argument('--num_epochs', default=1, type=int, help='Number of training epochs on a dataset of collected experiences of size batch_size x num_batches_per_epoch')
    p.add_argument(
        '--rollout', default=32, type=int,
        help='Length of the rollout from each environment in timesteps.'
             'Once we collect this many timesteps on actor worker, we send this trajectory to the learner.'
             'The length of the rollout will determine how many timesteps are used to calculate bootstrapped'
             'Monte-Carlo estimates of discounted rewards, advantages, GAE, or V-trace targets. Shorter rollouts'
             'reduce variance, but the estimates are less precise (bias vs variance tradeoff).'
             'For RNN policies, this should be a multiple of --recurrence, so every rollout will be split'
             'into (n = rollout / recurrence) segments for backpropagation. V-trace algorithm currently requires that'
             'rollout == recurrence, which what you want most of the time anyway.'
             'Rollout length is independent from the episode length. Episode length can be both shorter or longer than'
             'rollout, although for PBT training it is currently recommended that rollout << episode_len'
             '(see function finalize_trajectory in actor_worker.py)',
    )
    # TODO: force set recurrence to rollout len if we use rnns - we don't currently support unequal recurrence and rollout anyway
    p.add_argument(
        '--recurrence', default=32, type=int,
        help='Trajectory length for backpropagation through time. If recurrence=1 there is no backpropagation through time, and experience is shuffled completely randomly'
             'For V-trace recurrence should be equal to rollout length.',
    )
    p.add_argument(
        '--shuffle_minibatches', default=True, type=str2bool,
        help='Whether to randomize and shuffle minibatches between iterations (this is a slow operation when batches are large, disabling this increases learner throughput when training with multiple epochs/minibatches per epoch)'
    )

    # basic RL parameters
    p.add_argument('--gamma', default=0.99, type=float, help='Discount factor')
    p.add_argument(
        '--reward_scale', default=1.0, type=float,
        help=('Multiply all rewards by this factor before feeding into RL algorithm.'
              'Sometimes the overall scale of rewards is too high which makes value estimation a harder regression task.'
              'Loss values become too high which requires a smaller learning rate, etc.'),
    )
    p.add_argument('--reward_clip', default=1000.0, type=float, help='Clip rewards between [-c, c]. Default [-1000, 1000] should mean no clipping for most envs (unless rewards are very large/small)')
    p.add_argument(
        '--value_bootstrap', default=False, type=str2bool,
        help='Bootstrap returns from value estimates if episode is terminated by timeout. More info here: https://github.com/Denys88/rl_games/issues/128',
    )

    # components of the loss function
    p.add_argument('--exploration_loss_coeff', default=0.003, type=float, help='Coefficient for the exploration component of the loss function.')
    p.add_argument('--value_loss_coeff', default=0.5, type=float, help='Coefficient for the critic loss')
    p.add_argument(
        '--kl_loss_coeff', default=0.0, type=float,
        help='Coefficient for fixed KL loss (as used by Schulman et al. in https://arxiv.org/pdf/1707.06347.pdf). '
             'Highly recommended for environments with continuous action spaces.',
    )
    p.add_argument(
        '--exploration_loss', default='entropy', type=str, choices=['entropy', 'symmetric_kl'],
        help='Usually the exploration loss is based on maximizing the entropy of the probability'
             ' distribution. Note that mathematically maximizing entropy of the categorical probability '
             'distribution is exactly the same as minimizing the (regular) KL-divergence between'
             ' this distribution and a uniform prior. The downside of using the entropy term '
             '(or regular asymmetric KL-divergence) is the fact that penalty does not increase as '
             'probabilities of some actions approach zero. I.e. numerically, there is almost '
             'no difference between an action distribution with a probability epsilon > 0 for '
             'some action and an action distribution with a probability = zero for this action.'
             ' For many tasks the first (epsilon) distribution is preferrable because we keep some '
             '(albeit small) amount of exploration, while the second distribution will never explore '
             'this action ever again.'
             'Unlike the entropy term, symmetric KL divergence between the action distribution '
             'and a uniform prior approaches infinity when entropy of the distribution approaches zero,'
             ' so it can prevent the pathological situations where the agent stops exploring. '
             'Empirically, symmetric KL-divergence yielded slightly better results on some problems.',
    )

    # more specific to policy gradient algorithms or PPO
    p.add_argument('--gae_lambda', default=0.95, type=float, help='Generalized Advantage Estimation discounting (only used when V-trace is False)')
    p.add_argument('--ppo_clip_ratio', default=0.1, type=float, help='We use unbiased clip(x, 1+e, 1/(1+e)) instead of clip(x, 1+e, 1-e) in the paper')
    p.add_argument('--ppo_clip_value', default=1.0, type=float, help='Maximum absolute change in value estimate until it is clipped. Sensitive to value magnitude')
    p.add_argument('--with_vtrace', default=True, type=str2bool, help='Enables V-trace off-policy correction. If this is True, then GAE is not used')
    p.add_argument('--vtrace_rho', default=1.0, type=float, help='rho_hat clipping parameter of the V-trace algorithm (importance sampling truncation)')
    p.add_argument('--vtrace_c', default=1.0, type=float, help='c_hat clipping parameter of the V-trace algorithm. Low values for c_hat can reduce variance of the advantage estimates (similar to GAE lambda < 1)')

    # optimization
    p.add_argument('--optimizer', default='adam', type=str, choices=['adam', 'lamb'], help='Type of optimizer to use')
    p.add_argument('--adam_eps', default=1e-6, type=float, help='Adam epsilon parameter (1e-8 to 1e-5 seem to reliably work okay, 1e-3 and up does not work)')
    p.add_argument('--adam_beta1', default=0.9, type=float, help='Adam momentum decay coefficient')
    p.add_argument('--adam_beta2', default=0.999, type=float, help='Adam second momentum decay coefficient')
    p.add_argument('--max_grad_norm', default=4.0, type=float, help='Max L2 norm of the gradient vector, set to 0 to disable gradient clipping')

    # learning rate
    p.add_argument('--learning_rate', default=1e-4, type=float, help='LR')
    p.add_argument(
        '--lr_schedule', default='constant', choices=['constant', 'kl_adaptive_minibatch', 'kl_adaptive_epoch'], type=str,
        help=('Learning rate schedule to use. Constant keeps constant learning rate throughout training.'
              'kl_adaptive* schedulers look at --lr_schedule_kl_threshold and if KL-divergence with behavior policy'
              'after the last minibatch/epoch significantly deviates from this threshold, lr is apropriately'
              'increased or decreased'),
    )
    p.add_argument('--lr_schedule_kl_threshold', default=0.008, type=float, help='Used with kl_adaptive_* schedulers')

    # observation preprocessing
    p.add_argument('--obs_subtract_mean', default=0.0, type=float, help='Observation preprocessing, mean value to subtract from observation (e.g. 128.0 for 8-bit RGB)')
    p.add_argument('--obs_scale', default=1.0, type=float, help='Observation preprocessing, divide observation tensors by this scalar (e.g. 128.0 for 8-bit RGB)')
    p.add_argument('--normalize_input', default=False, type=str2bool, help='Whether to use running mean and standard deviation to normalize observations')

    # decorrelating experience on startup (optional)
    p.add_argument(
        '--decorrelate_experience_max_seconds', default=10, type=int,
        help='Decorrelating experience serves two benefits. First: this is better for learning because samples from workers come from random moments in the episode, becoming more "i.i.d".'
             'Second, and more important one: this is good for environments with highly non-uniform one-step times, including long and expensive episode resets. If experience is not decorrelated'
             'then training batches will come in bursts e.g. after a bunch of environments finished resets and many iterations on the learner might be required,'
             'which will increase the policy-lag of the new experience collected. The performance of the Sample Factory is best when experience is generated as more-or-less'
             'uniform stream. Try increasing this to 100-200 seconds to smoothen the experience distribution in time right from the beginning (it will eventually spread out and settle anyways)',
    )
    p.add_argument(
        '--decorrelate_envs_on_one_worker', default=True, type=str2bool,
        help='In addition to temporal decorrelation of worker processes, also decorrelate envs within one worker process. '
             'For environments with a fixed episode length it can prevent the reset from happening in the same rollout for all envs simultaneously, which makes experience collection more uniform.',
    )

    # performance optimizations
    p.add_argument('--actor_worker_gpus', default=[], type=int, nargs='*', help='By default, actor workers only use CPUs. Changes this if e.g. you need GPU-based rendering on the actors')
    p.add_argument(
        '--set_workers_cpu_affinity', default=True, type=str2bool,
        help='Whether to assign workers to specific CPU cores or not. The logic is beneficial for most workloads because prevents a lot of context switching.'
             'However for some environments it can be better to disable it, to allow one worker to use all cores some of the time. This can be the case for some DMLab environments with very expensive episode reset'
             'that can use parallel CPU cores for level generation.',
    )
    p.add_argument(
        '--force_envs_single_thread', default=True, type=str2bool,  # TODO: set to False?
        help='Some environments may themselves use parallel libraries such as OpenMP or MKL. Since we parallelize environments on the level of workers, there is no need to keep this parallel semantic.'
             'This flag uses threadpoolctl to force libraries such as OpenMP and MKL to use only a single thread within the environment.'
             'Default value (True) is recommended unless you are running fewer workers than CPU cores.',
    )
    p.add_argument('--default_niceness', default=0, type=int, help='Niceness of the highest priority process (the learner). Values below zero require elevated privileges.')

    # reporting summaries
    p.add_argument('--experiment_summaries_interval', default=10, type=int, help='How often in seconds we write avg. statistics about the experiment (reward, episode length, extra stats...)')
    p.add_argument('--stats_avg', default=100, type=int, help='How many episodes to average to measure performance (avg. reward etc)')

    # experiment termination
    p.add_argument('--train_for_env_steps', default=int(1e10), type=int, help='Stop after all policies are trained for this many env steps')
    p.add_argument('--train_for_seconds', default=int(1e10), type=int, help='Stop training after this many seconds')

    # model saving
    p.add_argument('--save_every_sec', default=120, type=int, help='Checkpointing rate')
    p.add_argument('--keep_checkpoints', default=3, type=int, help='Number of model checkpoints to keep')
    p.add_argument('--load_checkpoint_kind', default='latest', choices=['latest', 'best'], help='Whether to load from latest or best checkpoint')
    # TODO: check if this is working
    p.add_argument('--save_milestones_sec', default=-1, type=int, help='Save intermediate checkpoints in a separate folder for later evaluation (default=never)')
    p.add_argument('--save_best_every_sec', default=5, type=int, help='How often we check if we should save the policy with the best score ever')
    p.add_argument('--save_best_metric', default='reward', help='Save "best" policies based on this metric (just env reward by default)')

    # debugging options
    p.add_argument('--benchmark', default=False, type=str2bool, help='Benchmark mode')


def add_model_args(p: ArgumentParser):
    """Policy size, configuration, etc."""
    p.add_argument('--encoder_type', default='conv', type=str, help='Type of the encoder. Supported: conv, mlp, resnet (feel free to define more)')
    p.add_argument('--encoder_subtype', default='convnet_simple', type=str, help='Specific encoder design (see model.py)')
    p.add_argument('--encoder_custom', default=None, type=str, help='Use custom encoder class from the registry (see model_utils.py)')
    p.add_argument('--encoder_extra_fc_layers', default=1, type=int, help='Number of fully-connected layers of size "hidden size" to add after the basic encoder (e.g. convolutional)')
    p.add_argument('--hidden_size', default=512, type=int, help='Size of hidden layer in the model, or the size of RNN hidden state in recurrent model (e.g. GRU)')
    p.add_argument('--nonlinearity', default='elu', choices=['elu', 'relu', 'tanh'], type=str, help='Type of nonlinearity to use')
    p.add_argument('--policy_initialization', default='orthogonal', choices=['orthogonal', 'xavier_uniform', 'torch_default'], type=str, help='NN weight initialization')
    p.add_argument('--policy_init_gain', default=1.0, type=float, help='Gain parameter of PyTorch initialization schemas (i.e. Xavier)')
    p.add_argument('--actor_critic_share_weights', default=True, type=str2bool, help='Whether to share the weights between policy and value function')

    p.add_argument('--adaptive_stddev', default=True, type=str2bool, help='Only for continuous action distributions, whether stddev is state-dependent or just a single learned parameter')
    p.add_argument('--initial_stddev', default=1.0, type=float, help='Initial value for non-adaptive stddev. Only makes sense for continuous action spaces')

    # RNN settings
    p.add_argument('--use_rnn', default=True, type=str2bool, help='Whether to use RNN core in a policy or not')
    p.add_argument('--rnn_type', default='gru', choices=['gru', 'lstm'], type=str, help='Type of RNN cell to use if use_rnn is True')
    p.add_argument('--rnn_num_layers', default=1, type=int, help='Number of RNN layers to use if use_rnn is True')


def add_default_env_args(p: ArgumentParser):
    """Configuration related to the environments, i.e. things that might be difficult to query from an environment instance."""
    p.add_argument('--env_gpu_actions', default=False, type=str2bool, help='Set to true if environment expects actions on GPU (i.e. as a GPU-side PyTorch tensor)')

    p.add_argument('--env_frameskip', default=None, type=int, help='Number of frames for action repeat (frame skipping). Default (None) means use default environment value')
    p.add_argument('--env_framestack', default=4, type=int, help='Frame stacking (only used in Atari?)')
    p.add_argument('--pixel_format', default='CHW', type=str, help='PyTorch expects CHW by default, Ray & TensorFlow expect HWC')


def add_eval_args(parser):
    """Evaluation-related arguments, i.e. only used when testing/visualizing policies rather than training them."""
    parser.add_argument('--fps', default=0, type=int, help='Enable sync mode with adjustable FPS. Default (0) means default, e.g. for Doom its FPS (~35), or unlimited if not specified by env. Leave at 0 for Doom multiplayer evaluation')
    parser.add_argument('--render_action_repeat', default=None, type=int, help='Repeat an action that many frames during evaluation. By default uses the value from env config (used during training).')
    parser.add_argument('--no_render', action='store_true', help='Do not render the environment during evaluation')
    parser.add_argument('--policy_index', default=0, type=int, help='Policy to evaluate in case of multi-policy training')
    parser.add_argument('--record_to', default=join(os.getcwd(), '..', 'recs'), type=str, help='Record episodes to this folder. Only used for VizDoom!')

    parser.add_argument('--continuous_actions_sample', default=True, type=str2bool, help='True to sample from a continuous action distribution at test time, False to just take the mean')


def add_wandb_args(p: ArgumentParser):
    """Weights and Biases experiment monitoring."""
    p.add_argument('--with_wandb', default=False, type=str2bool, help='Enables Weights and Biases integration')
    p.add_argument('--wandb_user', default=None, type=str, help='WandB username (entity). Must be specified from command line! Also see https://docs.wandb.ai/quickstart#1.-set-up-wandb')
    p.add_argument('--wandb_project', default='sample_factory', type=str, help='WandB "Project"')
    p.add_argument('--wandb_group', default=None, type=str, help='WandB "Group" (to group your experiments). By default this is the name of the env.')
    p.add_argument('--wandb_job_type', default='SF', type=str, help='WandB job type')
    p.add_argument('--wandb_tags', default=[], type=str, nargs='*', help='Tags can help with finding experiments in WandB web console')


def add_pbt_args(p: ArgumentParser):
    """This is currently not supported and should be probably moved elsewhere."""  # TODO: PBT example
    p.add_argument('--with_pbt', default=False, type=str2bool, help='Enables population-based training basic features')
    p.add_argument('--pbt_mix_policies_in_one_env', default=True, type=str2bool, help='For multi-agent envs, whether we mix different policies in one env.')
    p.add_argument('--pbt_period_env_steps', default=int(5e6), type=int, help='Periodically replace the worst policies with the best ones and perturb the hyperparameters')
    p.add_argument('--pbt_start_mutation', default=int(2e7), type=int, help='Allow initial diversification, start PBT after this many env steps')
    p.add_argument('--pbt_replace_fraction', default=0.3, type=float, help='A portion of policies performing worst to be replace by better policies (rounded up)')
    p.add_argument('--pbt_mutation_rate', default=0.15, type=float, help='Probability that a parameter mutates')
    p.add_argument('--pbt_replace_reward_gap', default=0.1, type=float, help='Relative gap in true reward when replacing weights of the policy with a better performing one')
    p.add_argument('--pbt_replace_reward_gap_absolute', default=1e-6, type=float, help='Absolute gap in true reward when replacing weights of the policy with a better performing one')
    p.add_argument('--pbt_optimize_batch_size', default=False, type=str2bool, help='Whether to optimize batch size or not (experimental)')
    p.add_argument('--pbt_optimize_gamma', default=False, type=str2bool, help='Whether to optimize gamma, discount factor, or not (experimental)')
    p.add_argument(
        '--pbt_target_objective', default='true_objective', type=str,
        help='Policy stat to optimize with PBT. true_objective (default) is equal to raw env reward if not specified, but can also be any other per-policy stat.'
             'For DMlab-30 use value "dmlab_target_objective" (which is capped human normalized score)',
    )
    p.add_argument(
        '--pbt_perturb_min', default=1.05, type=float,
        help='When PBT mutates a float hyperparam, it samples the change magnitude randomly from the uniform distribution [pbt_perturb_min, pbt_perturb_max]',
    )
    p.add_argument(
        '--pbt_perturb_max', default=1.5, type=float,
        help='When PBT mutates a float hyperparam, it samples the change magnitude randomly from the uniform distribution [pbt_perturb_min, pbt_perturb_max]',
    )