from .signals import QtSignal


class vmmConnectionManager:
    _instance = None

    conn_added = QtSignal(object)
    conn_removed = QtSignal(str)

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = vmmConnectionManager()
        return cls._instance

    def __init__(self):
        self._conns = {}
        self._engine = None

    def set_engine(self, engine):
        self._engine = engine

    @property
    def conns(self):
        return self._conns.copy()

    def add_conn(self, uri):
        if uri in self._conns:
            return self._conns[uri]
        
        from ..models.connection import ConnectionModel
        conn = ConnectionModel(uri)
        self._conns[uri] = conn
        self.conn_added.emit(conn)
        return conn

    def remove_conn(self, uri):
        if uri not in self._conns:
            return
        
        conn = self._conns.pop(uri)
        self.conn_removed.emit(uri)

    def cleanup(self):
        for conn in list(self._conns.values()):
            uri = conn.get_uri()
            try:
                conn.close()
                self.conn_removed.emit(uri)
            except Exception:
                pass
        self._conns = {}
