from ..loggers import logger

import keras
from keras.models import load_model
from keras.callbacks import TensorBoard


class BaseModel:

    def __init__(self):
        self.log_dir = None
        self.model = None

    def compile(self, lr):
        self.model.compile(
            loss='categorical_crossentropy',
            optimizer=keras.optimizers.adam(lr=lr),  # decay=1e-6),
            metrics=['accuracy']
        )
        return self

    def fit(self, x_train, y_train, x_test, y_test, epochs, batch_size):
        self.model.fit(
            x_train, y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_data=(x_test, y_test),
            callbacks=[self.get_tensorboard()]
        )
        return self

    def get_tensorboard(self):
        return TensorBoard(log_dir=self.log_dir)

    def get_model(self):
        return self.model

    def save(self, fn):
        logger.debug(f'saved to {fn}')
        self.model.save(fn)
        return self

    def load(self, model_path):
        self.model = load_model(model_path)
        return self
