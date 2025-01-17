import pathlib
import torch
import sys

from components.episode_buffer import ReplayBuffer, EpisodeBatch

BATCH_DIM = 0
EPISODE_STEP_DIM = 1
AGENT_DIM = 2
FEATURE_DIM = -1


class Loader:

    def __init__(self, map_name, dataset_type, batch_size=None, smac_version=1, seed=0):
        self.map_name = map_name
        self.job_type = dataset_type
        self.dataset_dir = (
                pathlib.Path(__file__).parent.resolve() / f"smac_{smac_version}" / map_name / str(seed) / dataset_type
        )  # type: pathlib.Path
        self.dataset_args = torch.load(self.dataset_dir / "dataset_args.pkl")

        feature_names = torch.load(self.dataset_dir / "feature_names.pkl")
        self.state_feature_names, self.obs_feature_names = feature_names["state"], feature_names["observations"]
        self.episode_buffer = torch.load(self.dataset_dir / "eval_buffer.pth")  # type: ReplayBuffer
        self.episode_buffer.pin_memory()
        self.batch_size = batch_size
        self.nb_batch = len(self) // self.batch_size

    def __len__(self):
        return self.episode_buffer.episodes_in_buffer

    def sample_batches(self, device):
        for _ in range(self.nb_batch):
            episode_sample = self.episode_buffer.sample(self.batch_size)  # type: EpisodeBatch
            max_ep_t = episode_sample.max_t_filled()
            episode_sample = episode_sample[:, :max_ep_t]
            episode_sample.to(device)
            yield episode_sample

    def get_validation_batches(self, device, max_seq_length=None):
        for i in range(self.nb_batch):
            episode_sample = self.episode_buffer[i * self.batch_size: (i + 1) * self.batch_size]
            if max_seq_length is not None:
                episode_sample = episode_sample[:, :max_seq_length]
            episode_sample.to(device)
            yield episode_sample


class Mask:
    def __init__(self, obs_features=None, state_features="same_as_obs", exception=None):
        if obs_features is None:
            self.obs_features = []
        else:
            self.obs_features = obs_features
        if state_features == "same_as_obs":
            self.state_features = self.obs_features
        else:
            self.state_features = state_features
        self.exception = exception
        self.nb_masks = 1

    @staticmethod
    def mask_feature(mask_substrings, exception, feature_names, sample, is_state):
        if len(mask_substrings) == 0:
            return
        for i, feature in enumerate(feature_names):
            for mask_substring in mask_substrings:
                if mask_substring in feature:
                    if exception is None or exception not in feature:
                        if is_state:
                            sample[:, :, i] = 0
                        else:
                            sample[:, :, :, i] = 0
                        break

    def apply(self, episode_sample, state_feature_names, obs_feature_names):
        self.mask_feature(self.state_features, self.exception, state_feature_names, episode_sample["state"],
                          is_state=True)
        self.mask_feature(self.obs_features, self.exception, obs_feature_names, episode_sample["obs"],
                          is_state=False)


features_to_mask_map = dict(
    nothing=Mask(),
    everything=Mask(["_", "timestep"]),
    ally_all=Mask(["ally"]),
    ally_all_except_actions=Mask(["ally"], exception="action"),
    ally_last_action_only=Mask(["ally_last_action"]),
    ally_health=Mask(["ally_health"]),
    ally_shield=Mask(["ally_shield"]),
    ally_health_and_shield=Mask(["ally_health", "ally_shield"]),
    ally_distance=Mask(["ally_distance", "ally_relative", "ally_visible"]),
    enemy_all=Mask(["enemy"]),
    enemy_health=Mask(["enemy_health"]),
    enemy_shield=Mask(["enemy_shield"]),
    enemy_health_and_shield=Mask(["enemy_health", "enemy_shield"]),
    enemy_distance=Mask(["enemy_distance", "enemy_relative", "enemy_shootable"]),
    own_health=Mask(["own_health"], state_features=["ally_heath"]),
    own_fov=Mask(["fov"]),
    own_position=Mask(["own_pos"], state_features=["ally_relative"]),
)


def build_mask(mask_name):
    return features_to_mask_map[mask_name]
